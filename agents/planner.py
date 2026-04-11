from __future__ import annotations

from uuid import uuid4

from actions.executor import simulate_actions
from agents.base import BaseAgent
from core.enums import ActionType, ApprovalStatus, ConstraintViolationCode, PlanStatus
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
        
        from policies.constraints import evaluate_hard_constraints, evaluate_soft_constraints
        
        feasible_candidates = []
        infeasible_reasons = {}
        for act in candidate_actions:
            dummy_plan = Plan(
                plan_id="tmp", mode=state.mode, 
                score=0, score_breakdown={}, actions=[act]
            )
            is_feas, vios = evaluate_hard_constraints(dummy_plan, state)
            if is_feas:
                feasible_candidates.append(act)
            else:
                infeasible_reasons[act.action_id] = vios
                
        if not feasible_candidates and candidate_actions:
            feasible_candidates = [
                Action(
                    action_id="act_no_op_fallback",
                    action_type=ActionType.NO_OP,
                    target_id="system",
                    reason="all candidate actions violated hard constraints",
                    priority=0.0
                )
            ]

        selected = _dedupe_actions(feasible_candidates, action_limit)
        
        # --- Strategic Memory Reasoning ---
        from policies.strategic_prompt import (
            retrieve_relevant_cases,
            compute_memory_influence,
            derive_strategy_rationale,
            build_strategic_prompt,
        )
        from core.models import PlanMetadata
        
        # Lấy event: ưu tiên event truyền vào, nếu không có thì lấy sự cố mới nhất trong state
        effective_event = event or (state.active_events[-1] if state.active_events else None)
        
        historical_cases = retrieve_relevant_cases(effective_event, state.memory, top_k=3)
        memory_influence = compute_memory_influence(historical_cases)
        
        # Build the strategic prompt
        strategic_prompt = build_strategic_prompt(
            mode=state.mode.value,
            event=effective_event,
            historical_cases=historical_cases,
            candidate_actions=feasible_candidates,
        )

        
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
        
        # Build plan object
        final_plan = Plan(
            plan_id=f"plan_{uuid4().hex[:8]}",
            mode=state.mode,
            trigger_event_ids=[event.event_id] if event else [],
            actions=selected,
            score=score,
            score_breakdown=breakdown,
            planner_reasoning=summary,
            status=PlanStatus.PROPOSED,
        )

        # Final plan-level feasibility check (Holistic check)
        is_hard_feas, hard_violations = evaluate_hard_constraints(final_plan, state)
        soft_violations = evaluate_soft_constraints(final_plan, state)
        
        final_plan.feasible = is_hard_feas
        final_plan.violations = hard_violations + soft_violations
        all_v_msgs = [v.message for v in final_plan.violations]
        if all_v_msgs:
            final_plan.mode_rationale = ("Hard violations: " if not is_hard_feas else "Soft warnings: ") + "; ".join(all_v_msgs)

        # Attach strategic memory metadata
        strategy_rationale = derive_strategy_rationale(effective_event, historical_cases, selected)
        final_plan.metadata = PlanMetadata(
            referenced_cases=[c.case_id for c in historical_cases],
            memory_influence_score=memory_influence,
            strategy_rationale=strategy_rationale,
            strategic_prompt=strategic_prompt
        )

            
        needs_approval, reason = approval_required(final_plan, before_kpis, simulated.kpis, event)
        final_plan.approval_required = needs_approval
        final_plan.approval_reason = reason
        winning_factors = build_winning_factors(selected, before_kpis, simulated.kpis, breakdown)
        rejection_reasons = explain_rejected_actions(
            candidate_actions, selected, action_limit, infeasible_reasons
        )

        decision_log = DecisionLog(
            decision_id=f"dec_{uuid4().hex[:8]}",
            plan_id=final_plan.plan_id,
            event_ids=final_plan.trigger_event_ids,
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
            feasible=final_plan.feasible,
            violations=final_plan.violations,
            mode_rationale=final_plan.mode_rationale,
            metadata=final_plan.metadata,
        )

        state.latest_plan = final_plan
        state.latest_plan_id = final_plan.plan_id
        state.pending_plan = final_plan if needs_approval else None
        state.decision_logs.append(decision_log)
        proposal.observations.append(f"built {final_plan.plan_id} with score {score:.4f}")
        proposal.notes_for_planner = final_plan.planner_reasoning
        return proposal
