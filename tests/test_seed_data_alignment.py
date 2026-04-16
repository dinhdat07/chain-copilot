from agents.demand import DemandAgent
from agents.inventory import InventoryAgent
from app_api.services import inventory_rows
from core.state import load_initial_state
from orchestrator.graph import build_graph
from simulation.scenarios import get_scenario_events


def test_seed_data_references_are_internally_consistent() -> None:
    state = load_initial_state()

    inventory_skus = set(state.inventory)
    warehouse_ids = set(state.warehouses)
    route_ids = set(state.routes)
    supplier_pairs = {
        (record.supplier_id, record.sku) for record in state.suppliers.values()
    }

    for item in state.inventory.values():
        assert item.preferred_route_id in route_ids
        assert item.warehouse_id in warehouse_ids
        assert (item.preferred_supplier_id, item.sku) in supplier_pairs

    for order in state.orders:
        assert order.sku in inventory_skus
        assert order.warehouse_id in warehouse_ids


def test_seed_scenarios_target_existing_entities() -> None:
    state = load_initial_state()
    inventory_skus = set(state.inventory)
    route_ids = set(state.routes)
    supplier_ids = {record.supplier_id for record in state.suppliers.values()}

    for scenario_name in [
        "supplier_delay",
        "demand_spike",
        "route_blockage",
        "compound_disruption",
    ]:
        for event in get_scenario_events(scenario_name):
            supplier_id = event.payload.get("supplier_id")
            sku = event.payload.get("sku")
            route_id = event.payload.get("route_id")

            if supplier_id is not None:
                assert supplier_id in supplier_ids
            if sku is not None:
                assert sku in inventory_skus
            if route_id is not None:
                assert route_id in route_ids


def test_seed_inventory_baseline_has_managed_low_stock_pressure() -> None:
    state = load_initial_state()
    DemandAgent().run(state, None)
    InventoryAgent().run(state, None)

    below_reorder = 0
    below_safety = 0
    for item in state.inventory.values():
        projected = item.on_hand + item.incoming_qty - item.forecast_qty
        below_reorder += projected < item.reorder_point
        below_safety += projected < item.safety_stock

    assert state.kpis.service_level >= 0.97
    assert state.kpis.stockout_risk <= 0.03
    assert 10 <= below_reorder <= 22
    assert below_safety <= 2


def test_inventory_api_status_matches_projected_low_stock_baseline() -> None:
    state = load_initial_state()
    DemandAgent().run(state, None)
    InventoryAgent().run(state, None)

    rows = inventory_rows(state)
    low_count = sum(row.status in {"low", "out_of_stock"} for row in rows)
    at_risk_count = sum(row.status == "at_risk" for row in rows)

    assert len(rows) == 50
    assert 3 <= low_count + at_risk_count <= 8
    assert low_count >= 3


def test_seed_warehouses_are_not_over_capacity_at_baseline() -> None:
    state = load_initial_state()

    for warehouse_id, warehouse in state.warehouses.items():
        current_stock = sum(
            item.on_hand + item.incoming_qty
            for item in state.inventory.values()
            if item.warehouse_id == warehouse_id
        )
        assert current_stock <= warehouse.capacity


def test_demand_spike_scenario_produces_actionable_plan(monkeypatch) -> None:
    monkeypatch.setenv("CHAINCOPILOT_LLM_ENABLED", "0")

    state = load_initial_state()
    event = get_scenario_events("demand_spike")[0]
    result = build_graph().invoke(state, event)

    assert result.latest_plan is not None
    assert any(
        action.action_type.value != "no_op" for action in result.latest_plan.actions
    )
    assert all(
        action.action_type.value != "no_op" for action in result.latest_plan.actions
    )
