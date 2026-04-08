from __future__ import annotations

from uuid import uuid4

from actions.executor import simulate_actions
from agents.base import BaseAgent
from core.enums import ActionType, ApprovalStatus, PlanStatus
from core.models import Action, AgentProposal, DecisionLog, Event, Plan, SystemState
from policies.explainability import (
    build_plan_summary,
    build_winning_factors,
    explain_rejected_actions,
)
from policies.guardrails import approval_required
from policies.scoring import compute_score


def _dedupe_actions(actions: list[Action], limit: int) -> list[Action]:
    selected: list[Action] = []
    seen: set[tuple[str, str]] = set()
    for action in sorted(actions, key=lambda item: item.priority, reverse=True):
        key = (action.action_type.value, action.target_id)
        if key in seen:
            continue
        selected.append(action)
        seen.add(key)
        if len(selected) >= limit:
            break
    return selected


class PlannerAgent(BaseAgent):
    name = "planner"

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        candidate_actions = list(state.candidate_actions)
        if not candidate_actions:
            candidate_actions = [
                Action(
                    action_id="act_no_op",
                    action_type=ActionType.NO_OP,
                    target_id="system",
                    reason="no action required",
                    priority=0.1,
                )
            ]

        action_limit = 3 if state.mode.value == "crisis" else 2
        selected = _dedupe_actions(candidate_actions, action_limit)
        before_kpis = state.kpis.model_copy(deep=True)
        simulated = simulate_actions(state, selected)
        score, breakdown = compute_score(
            service_level=simulated.kpis.service_level,
            total_cost=simulated.kpis.total_cost,
            disruption_risk=simulated.kpis.disruption_risk,
            recovery_speed=simulated.kpis.recovery_speed,
            mode=state.mode,
            baseline_cost=before_kpis.total_cost,
        )
        summary = build_plan_summary(before_kpis, simulated.kpis, breakdown)
        plan = Plan(
            plan_id=f"plan_{uuid4().hex[:8]}",
            mode=state.mode,
            trigger_event_ids=[event.event_id] if event else [],
            actions=selected,
            score=score,
            score_breakdown=breakdown,
            planner_reasoning=summary,
            status=PlanStatus.PROPOSED,
        )
        needs_approval, reason = approval_required(plan, before_kpis, simulated.kpis, event)
        plan.approval_required = needs_approval
        plan.approval_reason = reason
        winning_factors = build_winning_factors(selected, before_kpis, simulated.kpis, breakdown)
        rejection_reasons = explain_rejected_actions(candidate_actions, selected, action_limit)

        decision_log = DecisionLog(
            decision_id=f"dec_{uuid4().hex[:8]}",
            plan_id=plan.plan_id,
            event_ids=plan.trigger_event_ids,
            before_kpis=before_kpis,
            after_kpis=simulated.kpis,
            selected_actions=[action.action_id for action in selected],
            rejected_actions=rejection_reasons,
            score_breakdown=breakdown,
            rationale=summary,
            winning_factors=winning_factors,
            approval_required=needs_approval,
            approval_reason=reason if needs_approval else "no approval required: thresholds not triggered",
            approval_status=ApprovalStatus.PENDING if needs_approval else ApprovalStatus.AUTO_APPLIED,
        )

        state.latest_plan = plan
        state.latest_plan_id = plan.plan_id
        state.pending_plan = plan if needs_approval else None
        state.decision_logs.append(decision_log)
        proposal.observations.append(f"built {plan.plan_id} with score {score:.4f}")
        proposal.notes_for_planner = plan.planner_reasoning
        return proposal
