from __future__ import annotations

from uuid import uuid4

from actions.executor import simulate_actions
from agents.base import BaseAgent
from core.enums import ActionType, ApprovalStatus, PlanStatus
from core.models import (
    Action,
    AgentProposal,
    CandidatePlanDraft,
    CandidatePlanEvaluation,
    DecisionLog,
    Event,
    Plan,
    SystemState,
)
from llm.service import enrich_plan_and_decision, generate_candidate_plan_drafts
from policies.explainability import (
    build_plan_summary,
    build_winning_factors,
    explain_rejected_actions,
)
from policies.guardrails import approval_required
from policies.scoring import compute_score


STRATEGY_ORDER = ("cost_first", "balanced", "resilience_first")


def _dedupe_actions(actions: list[Action], limit: int) -> list[Action]:
    selected: list[Action] = []
    seen: set[tuple[str, str]] = set()
    for action in actions:
        key = (action.action_type.value, action.target_id)
        if key in seen:
            continue
        selected.append(action)
        seen.add(key)
        if len(selected) >= limit:
            break
    return selected


def _fallback_sort_key(strategy_label: str, action: Action) -> tuple[float, float, float, float]:
    if strategy_label == "cost_first":
        return (
            action.estimated_cost_delta,
            action.estimated_recovery_hours,
            -action.estimated_service_delta,
            action.estimated_risk_delta,
        )
    if strategy_label == "resilience_first":
        return (
            action.estimated_risk_delta,
            action.estimated_recovery_hours,
            -action.estimated_service_delta,
            action.estimated_cost_delta,
        )
    return (
        -action.priority,
        action.estimated_risk_delta,
        -action.estimated_service_delta,
        action.estimated_cost_delta,
    )


def _strategy_reason(strategy_label: str) -> str:
    if strategy_label == "cost_first":
        return "fallback cost-first strategy favors lower incremental cost and operational simplicity"
    if strategy_label == "resilience_first":
        return "fallback resilience-first strategy favors risk reduction and faster recovery"
    return "fallback balanced strategy blends specialist priority, risk reduction, and service protection"


def _ensure_actions(candidate_actions: list[Action]) -> list[Action]:
    if candidate_actions:
        return list(candidate_actions)
    return [
        Action(
            action_id="act_no_op",
            action_type=ActionType.NO_OP,
            target_id="system",
            reason="no action required",
            priority=0.1,
        )
    ]


def _action_limit_for_mode(state: SystemState) -> int:
    return 3 if state.mode.value == "crisis" else 2


def _fallback_drafts(candidate_actions: list[Action], action_limit: int) -> list[CandidatePlanDraft]:
    drafts: list[CandidatePlanDraft] = []
    for strategy_label in STRATEGY_ORDER:
        sorted_actions = sorted(candidate_actions, key=lambda action: _fallback_sort_key(strategy_label, action))
        selected = _dedupe_actions(sorted_actions, action_limit)
        drafts.append(
            CandidatePlanDraft(
                strategy_label=strategy_label,
                action_ids=[action.action_id for action in selected],
                rationale=_strategy_reason(strategy_label),
                llm_used=False,
            )
        )
    return drafts


def _normalize_drafts(
    drafts: list[CandidatePlanDraft],
    candidate_actions: list[Action],
    action_limit: int,
) -> tuple[list[CandidatePlanDraft], int]:
    allowed_ids = {action.action_id for action in candidate_actions}
    by_id = {action.action_id: action for action in candidate_actions}
    normalized: list[CandidatePlanDraft] = []
    repaired_count = 0
    fallback_map = {draft.strategy_label: draft for draft in _fallback_drafts(candidate_actions, action_limit)}
    draft_map = {draft.strategy_label: draft for draft in drafts if draft.strategy_label in STRATEGY_ORDER}

    for strategy_label in STRATEGY_ORDER:
        draft = draft_map.get(strategy_label)
        if draft is None:
            normalized.append(fallback_map[strategy_label])
            repaired_count += 1
            continue
        action_ids = [action_id for action_id in draft.action_ids if action_id in allowed_ids]
        selected_actions = _dedupe_actions(
            [by_id[action_id] for action_id in action_ids if action_id in by_id],
            action_limit,
        )
        if not selected_actions:
            normalized.append(fallback_map[strategy_label])
            repaired_count += 1
            continue
        normalized.append(
            CandidatePlanDraft(
                strategy_label=strategy_label,
                action_ids=[action.action_id for action in selected_actions],
                rationale=draft.rationale or _strategy_reason(strategy_label),
                llm_used=draft.llm_used,
            )
        )
    return normalized, repaired_count


def _evaluate_candidate(
    *,
    state: SystemState,
    event: Event | None,
    before_kpis,
    strategy_label: str,
    actions: list[Action],
    rationale: str,
    llm_used: bool,
) -> CandidatePlanEvaluation:
    simulated = simulate_actions(state, actions)
    score, breakdown = compute_score(
        service_level=simulated.kpis.service_level,
        total_cost=simulated.kpis.total_cost,
        disruption_risk=simulated.kpis.disruption_risk,
        recovery_speed=simulated.kpis.recovery_speed,
        mode=state.mode,
        baseline_cost=before_kpis.total_cost,
    )
    transient_plan = Plan(
        plan_id=f"plan_eval_{uuid4().hex[:8]}",
        mode=state.mode,
        trigger_event_ids=[event.event_id] if event else [],
        actions=actions,
        score=score,
        score_breakdown=breakdown,
        strategy_label=strategy_label,
        generated_by="llm" if llm_used else "deterministic_fallback",
        planner_reasoning=rationale,
        status=PlanStatus.PROPOSED,
    )
    needs_approval, reason = approval_required(transient_plan, before_kpis, simulated.kpis, event)
    return CandidatePlanEvaluation(
        strategy_label=strategy_label,
        action_ids=[action.action_id for action in actions],
        score=score,
        score_breakdown=breakdown,
        projected_kpis=simulated.kpis,
        approval_required=needs_approval,
        approval_reason=reason if needs_approval else "no approval required: thresholds not triggered",
        rationale=rationale,
        llm_used=llm_used,
    )


def _select_best_evaluation(evaluations: list[CandidatePlanEvaluation]) -> CandidatePlanEvaluation:
    return max(
        evaluations,
        key=lambda item: (
            item.score,
            -item.projected_kpis.disruption_risk,
            item.projected_kpis.service_level,
            -item.projected_kpis.total_cost,
            1 if item.strategy_label == "balanced" else 0,
        ),
    )


def _selection_reason(selected: CandidatePlanEvaluation, evaluations: list[CandidatePlanEvaluation]) -> str:
    ordered = sorted(
        evaluations,
        key=lambda item: (
            item.score,
            -item.projected_kpis.disruption_risk,
            item.projected_kpis.service_level,
            -item.projected_kpis.total_cost,
        ),
        reverse=True,
    )
    runner_up = ordered[1] if len(ordered) > 1 else None
    base = (
        f"selected {selected.strategy_label} because it produced the strongest deterministic score "
        f"({selected.score:.4f})"
    )
    if runner_up is None:
        return base
    return (
        f"{base} over {runner_up.strategy_label} ({runner_up.score:.4f}) after applying score, "
        "risk, service-level, and cost tie-breaks"
    )


class PlannerAgent(BaseAgent):
    name = "planner"

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        candidate_actions = _ensure_actions(state.candidate_actions)
        before_kpis = state.kpis.model_copy(deep=True)
        action_limit = _action_limit_for_mode(state)
        llm_drafts, planner_error = generate_candidate_plan_drafts(
            state=state,
            event=event,
            candidate_actions=candidate_actions,
        )
        drafts, repaired_count = _normalize_drafts(llm_drafts, candidate_actions, action_limit)
        fallback_used = repaired_count > 0
        if fallback_used and not planner_error:
            planner_error = "planner returned incomplete or invalid candidate plans"

        by_id = {action.action_id: action for action in candidate_actions}
        evaluations: list[CandidatePlanEvaluation] = []
        for draft in drafts:
            actions = [by_id[action_id] for action_id in draft.action_ids if action_id in by_id]
            evaluations.append(
                _evaluate_candidate(
                    state=state,
                    event=event,
                    before_kpis=before_kpis,
                    strategy_label=draft.strategy_label,
                    actions=actions,
                    rationale=draft.rationale,
                    llm_used=draft.llm_used,
                )
            )

        selected_evaluation = _select_best_evaluation(evaluations)
        selected_actions = [by_id[action_id] for action_id in selected_evaluation.action_ids if action_id in by_id]
        summary = build_plan_summary(
            before_kpis,
            selected_evaluation.projected_kpis,
            selected_evaluation.score_breakdown,
        )
        plan = Plan(
            plan_id=f"plan_{uuid4().hex[:8]}",
            mode=state.mode,
            trigger_event_ids=[event.event_id] if event else [],
            actions=selected_actions,
            score=selected_evaluation.score,
            score_breakdown=selected_evaluation.score_breakdown,
            strategy_label=selected_evaluation.strategy_label,
            generated_by=(
                "llm_planner"
                if repaired_count == 0
                else "llm_planner_repaired"
                if repaired_count < len(STRATEGY_ORDER)
                else "hybrid_fallback"
            ),
            approval_required=selected_evaluation.approval_required,
            approval_reason=selected_evaluation.approval_reason if selected_evaluation.approval_required else "",
            planner_reasoning=summary,
            status=PlanStatus.PROPOSED,
        )
        winning_factors = build_winning_factors(
            selected_actions,
            before_kpis,
            selected_evaluation.projected_kpis,
            selected_evaluation.score_breakdown,
        )
        rejection_reasons = explain_rejected_actions(candidate_actions, selected_actions, action_limit)
        decision_log = DecisionLog(
            decision_id=f"dec_{uuid4().hex[:8]}",
            plan_id=plan.plan_id,
            event_ids=plan.trigger_event_ids,
            before_kpis=before_kpis,
            after_kpis=selected_evaluation.projected_kpis,
            selected_actions=[action.action_id for action in selected_actions],
            rejected_actions=rejection_reasons,
            score_breakdown=selected_evaluation.score_breakdown,
            rationale=summary,
            candidate_evaluations=evaluations,
            selection_reason=_selection_reason(selected_evaluation, evaluations),
            winning_factors=winning_factors,
            approval_required=selected_evaluation.approval_required,
            approval_reason=selected_evaluation.approval_reason,
            approval_status=ApprovalStatus.PENDING if selected_evaluation.approval_required else ApprovalStatus.AUTO_APPLIED,
            planner_error=planner_error if fallback_used else None,
        )
        enrich_plan_and_decision(
            state=state,
            event=event,
            plan=plan,
            decision_log=decision_log,
        )

        state.latest_plan = plan
        state.latest_plan_id = plan.plan_id
        state.pending_plan = plan if plan.approval_required else None
        state.decision_logs.append(decision_log)
        proposal.observations.append(
            f"built {plan.plan_id} using {plan.strategy_label} with score {plan.score:.4f}"
        )
        if fallback_used and planner_error:
            proposal.risks.append(
                f"planner {'repair' if repaired_count < len(STRATEGY_ORDER) else 'fallback'} used: {planner_error}"
            )
        proposal.domain_summary = plan.generated_by or ""
        proposal.notes_for_planner = decision_log.selection_reason
        proposal.llm_used = any(evaluation.llm_used for evaluation in evaluations)
        proposal.llm_error = planner_error if fallback_used else None
        return proposal
