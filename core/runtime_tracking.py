from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from llm.config import load_settings

from core.models import DecisionLog, OrchestrationTrace, Plan, SystemState
from core.runtime_records import (
    DispatchMode,
    EventEnvelope,
    ExecutionRecord,
    ExecutionReceipt,
    ExecutionStatus,
    ExecutionSummary,
    ExecutionTransition,
    RunRecord,
    RunStatus,
    RunType,
    SelectedPlanSummary,
)
from core.state import utc_now


def new_run_id() -> str:
    return f"run_{uuid4().hex[:8]}"


def new_execution_id() -> str:
    return f"exec_{uuid4().hex[:8]}"


def new_event_envelope_id() -> str:
    return f"evt_env_{uuid4().hex[:8]}"


def new_correlation_id(prefix: str = "corr") -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def derive_fallback_reason(state: SystemState) -> str | None:
    settings = load_settings()
    if not settings.enabled:
        return "llm_disabled"
    reasons: list[str] = []
    if state.latest_trace is not None:
        for step in state.latest_trace.steps:
            if step.fallback_reason:
                reasons.append(step.fallback_reason)
    latest_decision = state.decision_logs[-1] if state.decision_logs else None
    if latest_decision is not None:
        for candidate in (
            latest_decision.planner_error,
            latest_decision.llm_error,
            latest_decision.critic_error,
        ):
            if candidate:
                reasons.append(candidate)
    return reasons[0] if reasons else None


def plan_summary(plan: Plan | None) -> SelectedPlanSummary | None:
    if plan is None:
        return None
    return SelectedPlanSummary(
        plan_id=plan.plan_id,
        strategy_label=plan.strategy_label,
        generated_by=plan.generated_by,
        approval_required=plan.approval_required,
        approval_reason=plan.approval_reason,
        score=plan.score,
        action_ids=[action.action_id for action in plan.actions],
    )


def execution_status_from_state(state: SystemState, decision: DecisionLog | None = None) -> ExecutionStatus:
    latest_trace = state.latest_trace
    if latest_trace is not None:
        status_map = {
            "pending_approval": ExecutionStatus.APPROVAL_PENDING,
            "approved_and_applied": ExecutionStatus.APPLIED,
            "auto_applied": ExecutionStatus.APPLIED,
            "rejected": ExecutionStatus.CANCELLED,
            "safer_plan_pending": ExecutionStatus.APPROVAL_PENDING,
            "safer_plan_auto_applied": ExecutionStatus.APPLIED,
            "no_op": ExecutionStatus.PLANNED,
        }
        if latest_trace.execution_status in status_map:
            return status_map[latest_trace.execution_status]
    if state.pending_plan is not None:
        return ExecutionStatus.APPROVAL_PENDING
    if state.latest_plan is not None:
        return ExecutionStatus.APPLIED
    if decision is not None and decision.approval_status.value == "rejected":
        return ExecutionStatus.CANCELLED
    return ExecutionStatus.PLANNED


def _transition(status: ExecutionStatus, reason: str, timestamp: datetime | None = None) -> ExecutionTransition:
    return ExecutionTransition(
        status=status,
        timestamp=timestamp or utc_now(),
        reason=reason,
    )


def _receipts_for_status(plan: Plan | None, status: ExecutionStatus) -> list[ExecutionReceipt]:
    if plan is None:
        return []
    if status not in {ExecutionStatus.APPLIED, ExecutionStatus.APPROVED, ExecutionStatus.DISPATCHED}:
        return []
    detail = "simulated action applied" if status == ExecutionStatus.APPLIED else "simulated action acknowledged"
    return [
        ExecutionReceipt(
            receipt_id=f"rcpt_{uuid4().hex[:8]}",
            action_id=action.action_id,
            status=status.value,
            detail=detail,
        )
        for action in plan.actions
    ]


def initial_execution_history(plan: Plan | None, status: ExecutionStatus) -> list[ExecutionTransition]:
    if plan is None:
        return [_transition(ExecutionStatus.PLANNED, "execution placeholder created")]
    history = [_transition(ExecutionStatus.PLANNED, "plan selected for execution lifecycle")]
    if status == ExecutionStatus.APPROVAL_PENDING:
        history.append(_transition(ExecutionStatus.APPROVAL_PENDING, "execution waiting for operator approval"))
    elif status == ExecutionStatus.APPLIED:
        history.append(_transition(ExecutionStatus.APPLIED, "execution auto-applied in simulation"))
    elif status == ExecutionStatus.CANCELLED:
        history.append(_transition(ExecutionStatus.CANCELLED, "execution cancelled"))
    return history


def build_execution_record(
    *,
    run_id: str,
    state: SystemState,
    decision: DecisionLog | None = None,
    execution_id: str | None = None,
    created_at: datetime | None = None,
) -> ExecutionRecord | None:
    plan = state.pending_plan or state.latest_plan
    if plan is None and decision is None:
        return None
    now = created_at or utc_now()
    summary = execution_summary(state, decision=decision)
    status = summary.status
    return ExecutionRecord(
        execution_id=execution_id or new_execution_id(),
        run_id=run_id,
        decision_id=decision.decision_id if decision else None,
        plan_id=plan.plan_id if plan else None,
        status=status,
        dispatch_mode=summary.dispatch_mode,
        dry_run=False,
        target_system="digital_twin",
        action_ids=summary.action_ids,
        receipts=_receipts_for_status(plan, status),
        status_history=initial_execution_history(plan, status),
        failure_reason=None,
        created_at=now,
        updated_at=now,
    )


def execution_summary(state: SystemState, decision: DecisionLog | None = None) -> ExecutionSummary | None:
    plan = state.pending_plan or state.latest_plan
    if plan is None and decision is None:
        return None
    actions = [action.action_id for action in plan.actions] if plan else []
    return ExecutionSummary(
        status=execution_status_from_state(state, decision=decision),
        dispatch_mode=DispatchMode.SIMULATION,
        action_ids=actions,
    )


def build_run_record(
    *,
    run_id: str,
    run_type: RunType,
    state: SystemState,
    started_at: datetime,
    parent_run_id: str | None = None,
    envelope: EventEnvelope | None = None,
    execution_id: str | None = None,
    status: RunStatus = RunStatus.COMPLETED,
) -> RunRecord:
    completed_at = utc_now()
    latest_decision = state.decision_logs[-1] if state.decision_logs else None
    fallback_reason = derive_fallback_reason(state)
    return RunRecord(
        run_id=run_id,
        run_type=run_type,
        parent_run_id=parent_run_id,
        correlation_id=envelope.correlation_id if envelope else new_correlation_id("run"),
        trigger_event_id=envelope.event_id if envelope else None,
        input_event_ids=[event.event_id for event in state.active_events],
        mode_before=state.latest_trace.mode_before if state.latest_trace else state.mode.value,
        mode_after=state.mode.value,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=round(max((completed_at - started_at).total_seconds() * 1000.0, 0.0), 2),
        decision_id=latest_decision.decision_id if latest_decision else None,
        selected_plan_id=state.latest_plan_id,
        execution_id=execution_id,
        approval_status=latest_decision.approval_status.value if latest_decision else None,
        llm_fallback_used=fallback_reason is not None,
        llm_fallback_reason=fallback_reason,
        selected_plan_summary=plan_summary(state.pending_plan or state.latest_plan),
        execution_summary=execution_summary(state, decision=latest_decision),
    )


def clone_trace_for_run(trace: OrchestrationTrace | None, run_id: str) -> OrchestrationTrace | None:
    if trace is None:
        return None
    copied = trace.model_copy(deep=True)
    copied.run_id = run_id
    return copied


def advance_execution_record(
    execution: ExecutionRecord,
    *,
    run_id: str,
    decision_id: str | None,
    plan: Plan | None,
    status: ExecutionStatus,
    reason: str,
) -> ExecutionRecord:
    updated = execution.model_copy(deep=True)
    updated.run_id = run_id
    updated.decision_id = decision_id
    updated.plan_id = plan.plan_id if plan else updated.plan_id
    updated.action_ids = [action.action_id for action in plan.actions] if plan else updated.action_ids
    updated.status = status
    updated.updated_at = utc_now()
    updated.status_history.append(_transition(status, reason, updated.updated_at))
    if status == ExecutionStatus.APPLIED:
        updated.receipts = _receipts_for_status(plan, status)
    if status == ExecutionStatus.CANCELLED:
        updated.failure_reason = reason
    return updated
