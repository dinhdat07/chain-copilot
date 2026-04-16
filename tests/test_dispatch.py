from __future__ import annotations

import pytest

from core.enums import ActionType, ExecutionStatus, PlanExecutionStatus
from core.models import Action, Plan, Mode
from execution.dispatch_service import ActionDispatchService
from execution.models import make_idempotency_key, ExecutionRecord
from execution.state_machine import (
    InvalidTransitionError,
    compute_plan_execution_status,
    transition,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_action(action_type: ActionType = ActionType.REORDER, action_id: str = "act_1") -> Action:
    return Action(
        action_id=action_id,
        action_type=action_type,
        target_id="SKU_001",
        parameters={"quantity": 50},
        estimated_cost_delta=500.0,
        estimated_service_delta=0.1,
        estimated_risk_delta=-0.05,
        estimated_recovery_hours=24.0,
        reason="test",
        priority=0.8,
    )


def _make_plan(actions: list[Action] | None = None) -> Plan:
    from core.enums import PlanStatus
    return Plan(
        plan_id="plan_test_001",
        mode=Mode.NORMAL,
        actions=actions or [_make_action()],
        score=0.5,
        score_breakdown={},
        status=PlanStatus.APPROVED,
    )


# ---------------------------------------------------------------------------
# 1. Idempotency Key
# ---------------------------------------------------------------------------

def test_idempotency_key_is_deterministic():
    key1 = make_idempotency_key("plan_a", "act_1", "2024-01-01T00:00:00")
    key2 = make_idempotency_key("plan_a", "act_1", "2024-01-01T00:00:00")
    assert key1 == key2


def test_idempotency_key_differs_on_different_inputs():
    key1 = make_idempotency_key("plan_a", "act_1", "2024-01-01T00:00:00")
    key2 = make_idempotency_key("plan_b", "act_1", "2024-01-01T00:00:00")
    assert key1 != key2


# ---------------------------------------------------------------------------
# 2. State Machine
# ---------------------------------------------------------------------------

def _make_record(status: ExecutionStatus = ExecutionStatus.PLANNED) -> ExecutionRecord:
    return ExecutionRecord(
        execution_id="exec_001",
        plan_id="plan_001",
        action_id="act_001",
        action_type="reorder",
        target_system="ERP",
        idempotency_key="abc123",
        status=status,
    )


def test_valid_transition_planned_to_approved():
    record = _make_record(ExecutionStatus.PLANNED)
    transition(record, ExecutionStatus.APPROVED)
    assert record.status == ExecutionStatus.APPROVED


def test_invalid_transition_raises():
    record = _make_record(ExecutionStatus.PLANNED)
    with pytest.raises(InvalidTransitionError):
        transition(record, ExecutionStatus.APPLIED)   # PLANNED → APPLIED is not allowed


def test_terminal_state_cannot_transition():
    record = _make_record(ExecutionStatus.APPLIED)
    with pytest.raises(InvalidTransitionError):
        transition(record, ExecutionStatus.DISPATCHED)


# ---------------------------------------------------------------------------
# 3. Plan-level status aggregation
# ---------------------------------------------------------------------------

def _record_with_status(status: ExecutionStatus) -> ExecutionRecord:
    r = _make_record()
    r.status = status
    return r


def test_all_applied_returns_completed():
    records = [_record_with_status(ExecutionStatus.APPLIED) for _ in range(3)]
    assert compute_plan_execution_status(records) == PlanExecutionStatus.COMPLETED


def test_partial_failure_returns_manual_intervention():
    records = [
        _record_with_status(ExecutionStatus.APPLIED),
        _record_with_status(ExecutionStatus.FAILED),
    ]
    assert compute_plan_execution_status(records) == PlanExecutionStatus.REQUIRES_MANUAL_INTERVENTION


def test_all_failed_returns_manual_intervention():
    records = [_record_with_status(ExecutionStatus.FAILED) for _ in range(2)]
    assert compute_plan_execution_status(records) == PlanExecutionStatus.REQUIRES_MANUAL_INTERVENTION


# ---------------------------------------------------------------------------
# 4. ActionDispatchService — dry_run always succeeds
# ---------------------------------------------------------------------------

def test_dry_run_always_succeeds():
    service = ActionDispatchService()
    plan = _make_plan()
    summary = service.dispatch_plan(plan, mode="dry_run")

    assert summary.plan_id == plan.plan_id
    assert summary.dispatch_mode == "dry_run"
    assert len(summary.records) == 1
    record = summary.records[0]
    assert record.status == ExecutionStatus.APPLIED
    assert record.receipt.get("status") == "DRY_RUN_OK"


def test_dry_run_noop_action_is_skipped():
    plan = _make_plan(actions=[
        _make_action(ActionType.NO_OP, "act_noop"),
    ])
    service = ActionDispatchService()
    summary = service.dispatch_plan(plan, mode="dry_run")
    assert len(summary.records) == 0   # NO_OP is skipped


def test_multiple_actions_dispatched():
    plan = _make_plan(actions=[
        _make_action(ActionType.REORDER,         "act_1"),
        _make_action(ActionType.REROUTE,         "act_2"),
        _make_action(ActionType.SWITCH_SUPPLIER, "act_3"),
    ])
    service = ActionDispatchService()
    summary = service.dispatch_plan(plan, mode="dry_run")
    assert len(summary.records) == 3
    for r in summary.records:
        assert r.status == ExecutionStatus.APPLIED


# ---------------------------------------------------------------------------
# 5. Routing — correct adapter is selected
# ---------------------------------------------------------------------------

def test_reorder_routes_to_erp():
    service = ActionDispatchService()
    plan = _make_plan(actions=[_make_action(ActionType.REORDER)])
    summary = service.dispatch_plan(plan, mode="dry_run")
    assert summary.records[0].target_system == "ERP"


def test_reroute_routes_to_tms():
    service = ActionDispatchService()
    plan = _make_plan(actions=[_make_action(ActionType.REROUTE)])
    summary = service.dispatch_plan(plan, mode="dry_run")
    assert summary.records[0].target_system == "TMS"


def test_rebalance_routes_to_wms():
    service = ActionDispatchService()
    plan = _make_plan(actions=[_make_action(ActionType.REBALANCE)])
    summary = service.dispatch_plan(plan, mode="dry_run")
    assert summary.records[0].target_system == "WMS"


# ---------------------------------------------------------------------------
# 6. Idempotency — same key returns cached receipt
# ---------------------------------------------------------------------------

def test_adapter_returns_cached_receipt_on_duplicate_key():
    from execution.adapters.stubs import ERPAdapter
    from execution.models import ExecutionRecord

    adapter = ERPAdapter()
    record = ExecutionRecord(
        execution_id="exec_idem",
        plan_id="plan_x",
        action_id="act_x",
        action_type="reorder",
        target_system="ERP",
        idempotency_key="unique_key_abc",
    )

    # First call (commit)
    result1 = adapter.dispatch(record, dry_run=False)
    # Second call with same key
    result2 = adapter.dispatch(record, dry_run=False)

    if result1.success:
        assert result1.receipt == result2.receipt   # same receipt returned
