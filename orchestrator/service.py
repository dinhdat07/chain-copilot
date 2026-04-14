from __future__ import annotations

from typing import Any
from uuid import uuid4

from actions.executor import simulate_actions
from core.enums import ActionType, ApprovalStatus, Mode, PlanStatus
from core.memory import SQLiteStore
from core.models import (
    Action,
    CandidatePlanEvaluation,
    DecisionLog,
    Event,
    Plan,
    SystemState,
    TraceRouteDecision,
    TraceStep,
)
from core.state import load_initial_state, utc_now
from llm.service import enrich_plan_and_decision
from orchestrator.graph import build_graph
from policies.explainability import (
    build_plan_summary,
    build_winning_factors,
    explain_rejected_actions,
)
from policies.guardrails import approval_required
from policies.scoring import compute_score
from simulation.learning import finalize_latest_scenario_run


class PendingApprovalError(RuntimeError):
    pass


def _latest_event(state: SystemState) -> Event | None:
    if not state.active_events:
        return None
    return state.active_events[-1]


def _save_state(state: SystemState, store: SQLiteStore) -> None:
    store.save_state(state)
    for decision_log in state.decision_logs:
        store.save_decision_log(decision_log)


def ensure_no_pending_plan(state: SystemState) -> None:
    if state.pending_plan is not None:
        raise PendingApprovalError(
            "resolve the pending approval before running another daily plan or scenario"
        )


def _current_pending_decision(state: SystemState, decision_id: str) -> DecisionLog:
    if not state.pending_plan or not state.decision_logs:
        raise ValueError("no pending decision")
    decision_log = state.decision_logs[-1]
    if decision_log.decision_id != decision_id:
        raise ValueError("decision not found")
    return decision_log


def _mode_from_state(state: SystemState) -> Mode:
    return Mode.CRISIS if state.active_events else Mode.NORMAL


def _append_approval_trace(
    state: SystemState,
    *,
    outcome: str,
    to_node: str,
    summary: str,
    execution_status: str,
    decision_id: str | None,
    approval_pending: bool,
) -> None:
    if state.latest_trace is None:
        return
    now = utc_now()
    state.latest_trace.current_branch = "approval"
    state.latest_trace.route_decisions.append(
        TraceRouteDecision(
            from_node="approval",
            outcome=outcome,
            to_node=to_node,
            reason=summary,
        )
    )
    state.latest_trace.steps.append(
        TraceStep(
            step_id=f"step_{uuid4().hex[:8]}",
            sequence=len(state.latest_trace.steps) + 1,
            node_key="approval_resolution",
            node_type="human_gate",
            status="completed",
            started_at=now,
            completed_at=now,
            duration_ms=0.0,
            mode_snapshot=state.mode.value,
            summary=summary,
            reasoning_source="human_approval_action",
            output_snapshot={
                "decision_id": decision_id,
                "action": outcome,
                "execution_status": execution_status,
                "approval_pending": approval_pending,
            },
        )
    )
    state.latest_trace.decision_id = decision_id
    state.latest_trace.approval_pending = approval_pending
    state.latest_trace.execution_status = execution_status
    state.latest_trace.terminal_stage = "approval" if approval_pending or to_node == "closed" else "execution"
    state.latest_trace.mode_after = state.mode.value
    state.latest_trace.completed_at = now
    state.latest_trace.status = "completed"


def _safer_action_key(action: Action) -> tuple[bool, float, float, float, float]:
    return (
        action.action_type == ActionType.NO_OP,
        action.estimated_risk_delta >= 0.0,
        action.estimated_risk_delta,
        action.estimated_cost_delta,
        action.estimated_recovery_hours - action.estimated_service_delta,
    )


def _merge_reason_parts(*parts: str) -> str:
    merged: list[str] = []
    for part in parts:
        value = part.strip()
        if not value:
            continue
        if value.startswith("no approval required"):
            continue
        if value not in merged:
            merged.append(value)
    return "; ".join(merged)


def _action_lookup_for_pending_context(state: SystemState) -> dict[str, Action]:
    by_id: dict[str, Action] = {}
    for action in state.candidate_actions:
        by_id[action.action_id] = action
    if state.latest_plan is not None:
        for action in state.latest_plan.actions:
            by_id.setdefault(action.action_id, action)
    if state.pending_plan is not None:
        for action in state.pending_plan.actions:
            by_id.setdefault(action.action_id, action)
    return by_id


def _build_safer_plan(state: SystemState, decision_log: DecisionLog) -> Plan:
    assert state.pending_plan is not None
    candidate_actions = list(state.pending_plan.actions)
    
    from policies.constraints import evaluate_hard_constraints, evaluate_soft_constraints
    
    feasible_candidates = []
    for act in candidate_actions:
        dummy_plan = Plan(
            plan_id="tmp", mode=state.mode, 
            score=0.0, score_breakdown={}, actions=[act]
        )
        is_feas, vios = evaluate_hard_constraints(dummy_plan, state)
        if is_feas:
            feasible_candidates.append(act)

    if not feasible_candidates:
        feasible_candidates = [
            Action(
                action_id="act_no_op_safer",
                action_type=ActionType.NO_OP,
                target_id="system",
                reason="no safer action available or feasible",
                priority=0.0,
            )
        ]
    selected_actions = sorted(feasible_candidates, key=_safer_action_key)[:1]
    target_mode = _mode_from_state(state)
    simulated = simulate_actions(state, selected_actions)
    score, breakdown = compute_score(
        service_level=simulated.kpis.service_level,
        total_cost=simulated.kpis.total_cost,
        disruption_risk=simulated.kpis.disruption_risk,
        recovery_speed=simulated.kpis.recovery_speed,
        mode=target_mode,
        baseline_cost=decision_log.before_kpis.total_cost,
    )
    plan = Plan(
        plan_id=f"plan_{uuid4().hex[:8]}",
        mode=target_mode,
        trigger_event_ids=[event.event_id for event in state.active_events],
        actions=selected_actions,
        score=score,
        score_breakdown=breakdown,
        strategy_label="safer_alternative",
        generated_by="operator_safer_request",
        planner_reasoning=build_plan_summary(decision_log.before_kpis, simulated.kpis, breakdown),
        status=PlanStatus.PROPOSED,
    )
    soft_violations = evaluate_soft_constraints(plan, state)
    plan.feasible = True
    plan.violations = soft_violations
    if soft_violations:
        plan.mode_rationale = "Soft constraints warnings: " + "; ".join(v.message for v in soft_violations)
        
    needs_approval, reason = approval_required(plan, decision_log.before_kpis, simulated.kpis, _latest_event(state))
    plan.approval_required = needs_approval
    plan.approval_reason = reason
    return plan


def _build_alternative_plan(
    *,
    state: SystemState,
    decision_log: DecisionLog,
    evaluation: CandidatePlanEvaluation,
) -> Plan:
    by_id = _action_lookup_for_pending_context(state)
    actions = [by_id[action_id] for action_id in evaluation.action_ids if action_id in by_id]
    if not actions:
        raise ValueError("selected alternative has no executable actions")

    target_mode = _mode_from_state(state)
    simulated = simulate_actions(state, actions)
    score, breakdown = compute_score(
        service_level=simulated.kpis.service_level,
        total_cost=simulated.kpis.total_cost,
        disruption_risk=simulated.kpis.disruption_risk,
        recovery_speed=simulated.kpis.recovery_speed,
        mode=target_mode,
        baseline_cost=decision_log.before_kpis.total_cost,
    )

    plan = Plan(
        plan_id=f"plan_{uuid4().hex[:8]}",
        mode=target_mode,
        trigger_event_ids=[event.event_id for event in state.active_events],
        actions=actions,
        score=score,
        score_breakdown=breakdown,
        strategy_label=evaluation.strategy_label,
        generated_by="operator_selected_alternative",
        planner_reasoning=evaluation.rationale
        or build_plan_summary(
            decision_log.before_kpis,
            simulated.kpis,
            breakdown,
            selected_actions=actions,
            strategy_label=evaluation.strategy_label,
            mode=target_mode,
            mode_rationale=evaluation.mode_rationale,
        ),
        status=PlanStatus.PROPOSED,
        feasible=evaluation.feasible,
        violations=list(evaluation.violations),
        mode_rationale=evaluation.mode_rationale,
    )

    from policies.constraints import evaluate_soft_constraints

    soft_violations = evaluate_soft_constraints(plan, state)
    if soft_violations:
        plan.violations = list(plan.violations) + soft_violations

    needs_approval, reason = approval_required(
        plan,
        decision_log.before_kpis,
        simulated.kpis,
        _latest_event(state),
    )
    plan.approval_required = True
    plan.approval_reason = _merge_reason_parts(
        f"operator selected alternative strategy ({evaluation.strategy_label})",
        evaluation.approval_reason,
        reason if needs_approval else "",
    ) or "operator selected alternative strategy and kept the plan in manual approval"
    return plan


def run_daily_plan(
    state: SystemState,
    store: SQLiteStore,
    graph: Any | None = None,
    run_id: str | None = None,
) -> SystemState:
    ensure_no_pending_plan(state)
    updated = (graph or build_graph()).invoke(state, None, run_id=run_id)
    _save_state(updated, store)
    return updated


def reset_runtime(store: SQLiteStore) -> SystemState:
    store.clear_all()
    return load_initial_state()


def approve_pending_plan(
    state: SystemState,
    store: SQLiteStore,
    decision_id: str,
    approve: bool,
    run_id: str | None = None,
) -> SystemState:
    if run_id is not None:
        state.run_id = run_id
    decision_log = _current_pending_decision(state, decision_id)
    pending_plan = state.pending_plan
    assert pending_plan is not None

    if approve:
        pending_plan.status = PlanStatus.APPROVED
        state.pending_plan = None
        updated = state
        if updated.latest_plan:
            updated.latest_plan.status = PlanStatus.APPROVED
        updated.mode = _mode_from_state(updated)
        updated.decision_logs[-1].approval_status = ApprovalStatus.APPROVED
        _append_approval_trace(
            updated,
            outcome="approve",
            to_node="execution",
            summary="operator approved the pending plan; execution is ready for dispatch",
            execution_status="approved_pending_dispatch",
            decision_id=decision_log.decision_id,
            approval_pending=False,
        )
    else:
        pending_plan.status = PlanStatus.REJECTED
        state.pending_plan = None
        state.mode = _mode_from_state(state)
        decision_log.approval_status = ApprovalStatus.REJECTED
        updated = state
        _append_approval_trace(
            updated,
            outcome="reject",
            to_node="closed",
            summary="operator rejected the pending plan; no actions were applied",
            execution_status="rejected",
            decision_id=decision_log.decision_id,
            approval_pending=False,
        )

    finalize_latest_scenario_run(updated)
    _save_state(updated, store)
    return updated


def request_safer_plan(
    state: SystemState,
    store: SQLiteStore,
    decision_id: str,
    run_id: str | None = None,
) -> SystemState:
    if run_id is not None:
        state.run_id = run_id
    previous_decision = _current_pending_decision(state, decision_id)
    if state.pending_plan is None:
        raise ValueError("no pending decision")
    if state.pending_plan.generated_by == "operator_safer_request":
        raise RuntimeError("safer alternative can only be requested once per approval cycle")

    previous_plan_actions = list(state.pending_plan.actions)
    state.pending_plan.status = PlanStatus.REJECTED
    previous_decision.approval_status = ApprovalStatus.REJECTED
    safer_plan = _build_safer_plan(state, previous_decision)
    safer_plan.approval_required = True
    safer_plan.approval_reason = _merge_reason_parts(
        safer_plan.approval_reason,
        "operator requested a safer alternative; manual approval is required before dispatch",
    )
    simulated = simulate_actions(state, safer_plan.actions)
    winning_factors = build_winning_factors(
        safer_plan.actions,
        previous_decision.before_kpis,
        simulated.kpis,
        safer_plan.score_breakdown,
    )
    rejection_reasons = explain_rejected_actions(previous_plan_actions, safer_plan.actions, 1)
    new_decision = DecisionLog(
        decision_id=f"dec_{uuid4().hex[:8]}",
        plan_id=safer_plan.plan_id,
        event_ids=safer_plan.trigger_event_ids,
        before_kpis=previous_decision.before_kpis.model_copy(deep=True),
        after_kpis=simulated.kpis,
        selected_actions=[action.action_id for action in safer_plan.actions],
        rejected_actions=rejection_reasons,
        score_breakdown=safer_plan.score_breakdown,
        rationale=safer_plan.planner_reasoning,
        selection_reason=(
            "Operator requested a safer alternative and the planner generated a lower-risk package for manual review."
        ),
        candidate_evaluations=previous_decision.candidate_evaluations,
        winning_factors=winning_factors,
        approval_required=True,
        approval_reason=safer_plan.approval_reason,
        approval_status=ApprovalStatus.PENDING,
        feasible=safer_plan.feasible,
        violations=safer_plan.violations,
        mode_rationale=safer_plan.mode_rationale,
    )
    enrich_plan_and_decision(
        state=state,
        event=_latest_event(state),
        plan=safer_plan,
        decision_log=new_decision,
    )

    state.latest_plan = safer_plan
    state.latest_plan_id = safer_plan.plan_id
    state.decision_logs.append(new_decision)
    state.pending_plan = safer_plan
    state.mode = Mode.APPROVAL
    updated = state
    _append_approval_trace(
        updated,
        outcome="safer_plan",
        to_node="approval",
        summary="operator requested a safer plan and a new approval candidate was generated",
        execution_status="safer_plan_pending",
        decision_id=new_decision.decision_id,
        approval_pending=True,
    )

    finalize_latest_scenario_run(updated)
    _save_state(updated, store)
    return updated


def select_pending_alternative_plan(
    state: SystemState,
    store: SQLiteStore,
    decision_id: str,
    strategy_label: str,
    run_id: str | None = None,
) -> SystemState:
    if run_id is not None:
        state.run_id = run_id
    previous_decision = _current_pending_decision(state, decision_id)
    if state.pending_plan is None:
        raise ValueError("no pending decision")

    normalized_label = strategy_label.strip().lower()
    evaluation = next(
        (
            item
            for item in previous_decision.candidate_evaluations
            if item.strategy_label.strip().lower() == normalized_label
        ),
        None,
    )
    if evaluation is None:
        raise ValueError(f"candidate strategy not found: {strategy_label}")
    if state.pending_plan.strategy_label == evaluation.strategy_label:
        raise RuntimeError(f"{evaluation.strategy_label} is already the selected pending strategy")

    previous_plan_actions = list(state.pending_plan.actions)
    state.pending_plan.status = PlanStatus.REJECTED
    previous_decision.approval_status = ApprovalStatus.REJECTED

    alternative_plan = _build_alternative_plan(
        state=state,
        decision_log=previous_decision,
        evaluation=evaluation,
    )
    simulated = simulate_actions(state, alternative_plan.actions)
    winning_factors = build_winning_factors(
        alternative_plan.actions,
        previous_decision.before_kpis,
        simulated.kpis,
        alternative_plan.score_breakdown,
    )
    rejection_reasons = explain_rejected_actions(
        previous_plan_actions,
        alternative_plan.actions,
        len(alternative_plan.actions),
    )

    selection_reason = (
        f"Operator selected the {evaluation.strategy_label} alternative for manual execution review."
    )
    new_decision = DecisionLog(
        decision_id=f"dec_{uuid4().hex[:8]}",
        plan_id=alternative_plan.plan_id,
        event_ids=alternative_plan.trigger_event_ids,
        before_kpis=previous_decision.before_kpis.model_copy(deep=True),
        after_kpis=simulated.kpis,
        selected_actions=[action.action_id for action in alternative_plan.actions],
        rejected_actions=rejection_reasons,
        score_breakdown=alternative_plan.score_breakdown,
        rationale=alternative_plan.planner_reasoning,
        selection_reason=selection_reason,
        candidate_evaluations=previous_decision.candidate_evaluations,
        winning_factors=winning_factors,
        approval_required=True,
        approval_reason=alternative_plan.approval_reason,
        approval_status=ApprovalStatus.PENDING,
        feasible=alternative_plan.feasible,
        violations=alternative_plan.violations,
        mode_rationale=alternative_plan.mode_rationale,
    )
    enrich_plan_and_decision(
        state=state,
        event=_latest_event(state),
        plan=alternative_plan,
        decision_log=new_decision,
    )

    state.latest_plan = alternative_plan
    state.latest_plan_id = alternative_plan.plan_id
    state.pending_plan = alternative_plan
    state.mode = Mode.APPROVAL
    state.decision_logs.append(new_decision)
    _append_approval_trace(
        state,
        outcome="select_alternative",
        to_node="approval",
        summary=selection_reason,
        execution_status="alternative_pending",
        decision_id=new_decision.decision_id,
        approval_pending=True,
    )

    finalize_latest_scenario_run(state)
    _save_state(state, store)
    return state
