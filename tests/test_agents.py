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
        entity_ids=["SUP_A", "SKU_1"],
        occurred_at=utc_now(),
        detected_at=utc_now(),
        payload={"supplier_id": "SUP_A", "sku": "SKU_1"},
        dedupe_key="evt_supplier_delay_test",
    )
    risk = RiskAgent().run(state, event)
    demand = DemandAgent().run(state, event)
    inventory = InventoryAgent().run(state, event)
    supplier = SupplierAgent().run(state, event)
    logistics = LogisticsAgent().run(state, event)

    assert state.mode == Mode.CRISIS
    assert risk.observations
    assert demand.observations
    assert inventory.proposals
    assert inventory.domain_summary
    assert "reorder point" in inventory.domain_summary
    assert supplier.proposals
    assert isinstance(logistics.proposals, list)
