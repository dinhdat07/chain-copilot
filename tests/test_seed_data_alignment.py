from core.state import load_initial_state
from simulation.scenarios import get_scenario_events


def test_seed_data_references_are_internally_consistent() -> None:
    state = load_initial_state()

    inventory_skus = set(state.inventory)
    warehouse_ids = set(state.warehouses)
    route_ids = set(state.routes)
    supplier_pairs = {
        (record.supplier_id, record.sku)
        for record in state.suppliers.values()
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
