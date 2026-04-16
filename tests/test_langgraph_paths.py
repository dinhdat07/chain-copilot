from core.enums import ApprovalStatus, EventType, Mode, PlanStatus
from core.models import Event
from core.state import load_initial_state, utc_now
from orchestrator.graph import build_graph


def _event(event_type: EventType, severity: float, payload: dict, entity_ids: list[str]) -> Event:
    return Event(
        event_id=f"evt_{event_type.value}_{severity}",
        type=event_type,
        source="test",
        severity=severity,
        entity_ids=entity_ids,
        occurred_at=utc_now(),
        detected_at=utc_now(),
        payload=payload,
        dedupe_key=f"{event_type.value}:{entity_ids}:{payload}",
    )


def test_langgraph_normal_path_executes_daily_plan() -> None:
    state = load_initial_state()
    result = build_graph().invoke(state, None)
    assert result.latest_plan is not None
    assert result.latest_plan.status == PlanStatus.APPLIED
    assert result.mode == Mode.NORMAL
    assert result.pending_plan is None


def test_langgraph_crisis_path_can_auto_apply() -> None:
    state = load_initial_state()
    event = _event(
        EventType.DEMAND_SPIKE,
        0.66,
        {"sku": "SKU_2", "multiplier": 1.4},
        ["SKU_2"],
    )
    result = build_graph().invoke(state, event)
    assert result.latest_plan is not None
    assert result.latest_plan.mode == Mode.CRISIS
    assert result.decision_logs[-1].approval_status in {
        ApprovalStatus.AUTO_APPLIED,
        ApprovalStatus.PENDING,
    }


def test_langgraph_approval_path_leaves_pending_plan() -> None:
    state = load_initial_state()
    event = _event(
        EventType.COMPOUND,
        0.92,
        {"supplier_id": "SUP_BN", "route_id": "R_BN_HN_MAIN", "sku": "SKU_001"},
        ["SUP_BN", "R_BN_HN_MAIN", "SKU_001"],
    )
    result = build_graph().invoke(state, event)
    assert result.mode == Mode.APPROVAL
    assert result.pending_plan is not None
    assert result.latest_plan is not None
    assert result.decision_logs[-1].approval_status == ApprovalStatus.PENDING
