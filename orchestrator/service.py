from __future__ import annotations

from typing import Any
from uuid import uuid4

from actions.executor import apply_plan, simulate_actions
from core.enums import ActionType, ApprovalStatus, Mode, PlanStatus
from core.memory import SQLiteStore
from core.models import Action, DecisionLog, Event, Plan, SystemState
from core.state import load_initial_state
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


def _safer_action_key(action: Action) -> tuple[bool, float, float, float, float]:
    return (
        action.action_type == ActionType.NO_OP,
        action.estimated_risk_delta >= 0.0,
        action.estimated_risk_delta,
        action.estimated_cost_delta,
        action.estimated_recovery_hours - action.estimated_service_delta,
    )


def _build_safer_plan(state: SystemState, decision_log: DecisionLog) -> Plan:
    assert state.pending_plan is not None
    candidate_actions = list(state.pending_plan.actions)
    if not candidate_actions:
        candidate_actions = [
            Action(
                action_id="act_no_op_safer",
                action_type=ActionType.NO_OP,
                target_id="system",
                reason="no safer action available",
                priority=0.0,
            )
        ]
    selected_actions = sorted(candidate_actions, key=_safer_action_key)[:1]
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
        planner_reasoning=build_plan_summary(decision_log.before_kpis, simulated.kpis, breakdown),
        status=PlanStatus.PROPOSED,
    )
    needs_approval, reason = approval_required(plan, decision_log.before_kpis, simulated.kpis, _latest_event(state))
    plan.approval_required = needs_approval
    plan.approval_reason = reason
    return plan


def run_daily_plan(
    state: SystemState,
    store: SQLiteStore,
    graph: Any | None = None,
) -> SystemState:
    ensure_no_pending_plan(state)
    updated = (graph or build_graph()).invoke(state, None)
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
) -> SystemState:
    decision_log = _current_pending_decision(state, decision_id)
    pending_plan = state.pending_plan
    assert pending_plan is not None

    if approve:
        pending_plan.status = PlanStatus.APPROVED
        updated = apply_plan(state, pending_plan)
        if updated.latest_plan:
            updated.latest_plan.status = PlanStatus.APPLIED
        updated.mode = _mode_from_state(updated)
        updated.decision_logs[-1].approval_status = ApprovalStatus.APPROVED
    else:
        pending_plan.status = PlanStatus.REJECTED
        state.pending_plan = None
        state.mode = _mode_from_state(state)
        decision_log.approval_status = ApprovalStatus.REJECTED
        updated = state

    finalize_latest_scenario_run(updated)
    _save_state(updated, store)
    return updated


def request_safer_plan(
    state: SystemState,
    store: SQLiteStore,
    decision_id: str,
) -> SystemState:
    previous_decision = _current_pending_decision(state, decision_id)
    if state.pending_plan is None:
        raise ValueError("no pending decision")

    previous_plan_actions = list(state.pending_plan.actions)
    state.pending_plan.status = PlanStatus.REJECTED
    previous_decision.approval_status = ApprovalStatus.REJECTED
    safer_plan = _build_safer_plan(state, previous_decision)
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
        winning_factors=winning_factors,
        approval_required=safer_plan.approval_required,
        approval_reason=(
            safer_plan.approval_reason
            if safer_plan.approval_required
            else "no approval required: thresholds not triggered"
        ),
        approval_status=ApprovalStatus.PENDING if safer_plan.approval_required else ApprovalStatus.AUTO_APPLIED,
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

    if safer_plan.approval_required:
        state.pending_plan = safer_plan
        state.mode = Mode.APPROVAL
        updated = state
    else:
        safer_plan.status = PlanStatus.APPLIED
        updated = apply_plan(state, safer_plan)
        updated.mode = _mode_from_state(updated)
        updated.decision_logs[-1].approval_status = ApprovalStatus.AUTO_APPLIED

    finalize_latest_scenario_run(updated)
    _save_state(updated, store)
    return updated
