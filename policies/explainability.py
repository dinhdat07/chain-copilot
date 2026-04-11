from __future__ import annotations

from core.models import Action, KPIState, Violation


def build_plan_summary(
    before_kpis: KPIState,
    after_kpis: KPIState,
    score_breakdown: dict[str, float],
) -> str:
    return (
        "Projected service level "
        f"{before_kpis.service_level:.1%} -> {after_kpis.service_level:.1%}, "
        f"total cost {before_kpis.total_cost:,.0f} -> {after_kpis.total_cost:,.0f}, "
        f"disruption risk {before_kpis.disruption_risk:.1%} -> {after_kpis.disruption_risk:.1%}, "
        f"recovery speed {before_kpis.recovery_speed:.1%} -> {after_kpis.recovery_speed:.1%}. "
        "Score contributions: "
        f"service level {score_breakdown.get('service_level', 0.0):+.3f}, "
        f"total cost {score_breakdown.get('total_cost', 0.0):+.3f}, "
        f"disruption risk {score_breakdown.get('disruption_risk', 0.0):+.3f}, "
        f"recovery speed {score_breakdown.get('recovery_speed', 0.0):+.3f}."
    )


def build_winning_factors(
    selected_actions: list[Action],
    before_kpis: KPIState,
    after_kpis: KPIState,
    score_breakdown: dict[str, float],
) -> list[str]:
    winning_factors = [
        (
            "Service level changed by "
            f"{after_kpis.service_level - before_kpis.service_level:+.1%} and contributed "
            f"{score_breakdown.get('service_level', 0.0):+.3f} to the score."
        ),
        (
            "Total cost changed by "
            f"{after_kpis.total_cost - before_kpis.total_cost:+,.2f} and contributed "
            f"{score_breakdown.get('total_cost', 0.0):+.3f} to the score."
        ),
        (
            "Disruption risk changed by "
            f"{after_kpis.disruption_risk - before_kpis.disruption_risk:+.1%} and contributed "
            f"{score_breakdown.get('disruption_risk', 0.0):+.3f} to the score."
        ),
        (
            "Recovery speed changed by "
            f"{after_kpis.recovery_speed - before_kpis.recovery_speed:+.1%} and contributed "
            f"{score_breakdown.get('recovery_speed', 0.0):+.3f} to the score."
        ),
    ]
    winning_factors.extend(
        [
            (
                f"{action.action_id} was selected because {action.reason}; "
                f"priority {action.priority:.2f}, service delta {action.estimated_service_delta:+.2f}, "
                f"risk delta {action.estimated_risk_delta:+.2f}, cost delta {action.estimated_cost_delta:+.2f}."
            )
            for action in selected_actions
        ]
    )
    return winning_factors


def explain_rejected_actions(
    candidate_actions: list[Action],
    selected_actions: list[Action],
    action_limit: int,
    infeasible_reasons: dict[str, list[Violation]] | None = None,
) -> list[dict[str, str]]:
    infeasible_reasons = infeasible_reasons or {}
    selected_by_key = {
        (action.action_type.value, action.target_id): action for action in selected_actions
    }
    selected_ids = {action.action_id for action in selected_actions}
    selected_priorities = [action.priority for action in selected_actions] or [0.0]
    selected_service = [action.estimated_service_delta for action in selected_actions] or [0.0]
    selected_risk = [action.estimated_risk_delta for action in selected_actions] or [0.0]
    threshold_priority = min(selected_priorities)
    avg_service = sum(selected_service) / len(selected_service)
    avg_risk = sum(selected_risk) / len(selected_risk)

    rejected_actions: list[dict[str, str]] = []
    for action in candidate_actions:
        if action.action_id in selected_ids:
            continue
        if action.action_id in infeasible_reasons:
            reason = "Hard constraint violation: " + "; ".join(v.message for v in infeasible_reasons[action.action_id])
        else:
            duplicate = selected_by_key.get((action.action_type.value, action.target_id))
            if duplicate is not None:
                reason = (
                    f"superseded by higher-priority {duplicate.action_id} on the same action target"
                )
            elif action.priority < threshold_priority:
                reason = (
                    f"lower priority ({action.priority:.2f}) than the chosen set threshold "
                    f"({threshold_priority:.2f}) under action limit {action_limit}"
                )
            elif action.estimated_risk_delta > avg_risk:
                reason = (
                    f"higher projected risk delta ({action.estimated_risk_delta:+.2f}) than the chosen "
                    f"set average ({avg_risk:+.2f})"
                )
            elif action.estimated_service_delta < avg_service:
                reason = (
                    f"lower projected service delta ({action.estimated_service_delta:+.2f}) than the "
                    f"chosen set average ({avg_service:+.2f})"
                )
            else:
                reason = "weaker overall trade-off than the chosen actions on priority and projected impact"
        rejected_actions.append({"action_id": action.action_id, "reason": reason})
    return rejected_actions
