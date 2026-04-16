from agents.demand import DemandAgent
from agents.inventory import InventoryAgent
from agents.logistics import LogisticsAgent
from agents.risk import RiskAgent
from agents.supplier import SupplierAgent
from core.enums import EventType, Mode
from core.models import Event
from core.state import load_initial_state, utc_now


def test_agents_emit_actions_for_supplier_delay() -> None:
    state = load_initial_state()
    event = Event(
        event_id="evt_supplier_delay_test",
        type=EventType.SUPPLIER_DELAY,
        source="test",
        severity=0.8,
        entity_ids=["SUP_BN", "SKU_001"],
        occurred_at=utc_now(),
        detected_at=utc_now(),
        payload={"supplier_id": "SUP_BN", "sku": "SKU_001"},
        dedupe_key="evt_supplier_delay_test",
    )
    risk = RiskAgent().run(state, event)
    demand = DemandAgent().run(state, event)
    inventory = InventoryAgent().run(state, event)
    supplier = SupplierAgent().run(state, event)
    logistics = LogisticsAgent().run(state, event)

    assert state.mode == Mode.CRISIS
    assert risk.domain_summary
    assert demand.observations
    assert inventory.proposals
    assert inventory.domain_summary
    assert "reorder point" in inventory.domain_summary
    assert supplier.proposals
    assert isinstance(logistics.proposals, list)


def test_route_blockage_actions_stay_within_blocked_lane_scope() -> None:
    state = load_initial_state()
    event = Event(
        event_id="evt_route_scope_test",
        type=EventType.ROUTE_BLOCKAGE,
        source="test",
        severity=0.78,
        entity_ids=["R_BN_HN_MAIN"],
        occurred_at=utc_now(),
        detected_at=utc_now(),
        payload={"route_ids": ["R_BN_HN_MAIN"], "reason": "flooding"},
        dedupe_key="evt_route_scope_test",
    )

    logistics = LogisticsAgent().run(state, event)
    inventory = InventoryAgent().run(state, event)

    logistics_targets = {action.target_id for action in logistics.proposals}
    inventory_targets = {action.target_id for action in inventory.proposals}

    assert logistics_targets
    assert all(
        state.inventory[sku].preferred_route_id == "R_BN_HN_MAIN"
        for sku in logistics_targets
    )
    assert all(
        state.inventory[sku].preferred_route_id == "R_BN_HN_MAIN"
        for sku in inventory_targets
    )
