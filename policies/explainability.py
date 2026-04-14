from __future__ import annotations

from core.enums import Mode
from core.models import (
    Action,
    CandidatePlanEvaluation,
    ConstraintViolation as Violation,
    KPIState,
    Plan,
)


def _pct(value: float) -> str:
    return f"{value:.1%}"


def _delta_pct(before: float, after: float) -> str:
    return f"{after - before:+.1%}"


def _delta_num(before: float, after: float) -> str:
    return f"{after - before:+,.0f}"


def _action_label(action: Action) -> str:
    action_name = action.action_type.value.replace("_", " ")
    return f"{action_name} on {action.target_id}"


def _mode_label(mode: Mode | str) -> str:
    value = mode.value if isinstance(mode, Mode) else mode
    return "crisis mode" if value == "crisis" else "normal mode"


def build_plan_summary(
    before_kpis: KPIState,
    after_kpis: KPIState,
    score_breakdown: dict[str, float],
    *,
    selected_actions: list[Action] | None = None,
    strategy_label: str | None = None,
    mode: Mode | str = Mode.NORMAL,
    runner_up: CandidatePlanEvaluation | None = None,
    mode_rationale: str = "",
) -> str:
    selected_actions = selected_actions or []
    action_text = (
        ", ".join(_action_label(action) for action in selected_actions[:3])
        if selected_actions
        else "no change to the operating plan"
    )
    comparison = ""
    if runner_up is not None:
        comparison = (
            f" It outperformed the main alternative ({runner_up.strategy_label}) after balancing "
            f"service, cost, disruption risk, and recovery speed."
        )
    mode_text = f"This recommendation is optimized for {_mode_label(mode)}."
    rationale_text = f" {mode_rationale}" if mode_rationale else ""
    return (
        f"Selected {strategy_label or 'current'} strategy using {action_text}. "
        f"Projected service level moves from {_pct(before_kpis.service_level)} to {_pct(after_kpis.service_level)}, "
        f"total cost changes by {_delta_num(before_kpis.total_cost, after_kpis.total_cost)}, "
        f"disruption risk changes by {_delta_pct(before_kpis.disruption_risk, after_kpis.disruption_risk)}, "
        f"and recovery speed changes by {_delta_pct(before_kpis.recovery_speed, after_kpis.recovery_speed)}."
        f"{comparison} {mode_text}{rationale_text}"
    ).strip()


def build_winning_factors(
    selected_actions: list[Action],
    before_kpis: KPIState,
    after_kpis: KPIState,
    score_breakdown: dict[str, float],
) -> list[str]:
    winning_factors = [
        (
            "Projected service level changed by "
            f"{_delta_pct(before_kpis.service_level, after_kpis.service_level)}; "
            f"score contribution {score_breakdown.get('service_level', 0.0):+.3f}."
        ),
        (
            "Projected total cost changed by "
            f"{_delta_num(before_kpis.total_cost, after_kpis.total_cost)}; "
            f"score contribution {score_breakdown.get('total_cost', 0.0):+.3f}."
        ),
        (
            "Projected disruption risk changed by "
            f"{_delta_pct(before_kpis.disruption_risk, after_kpis.disruption_risk)}; "
            f"score contribution {score_breakdown.get('disruption_risk', 0.0):+.3f}."
        ),
        (
            "Projected recovery speed changed by "
            f"{_delta_pct(before_kpis.recovery_speed, after_kpis.recovery_speed)}; "
            f"score contribution {score_breakdown.get('recovery_speed', 0.0):+.3f}."
        ),
    ]
    winning_factors.extend(
        [
            (
                f"{_action_label(action).capitalize()} was selected because {action.reason}. "
                f"Expected impact: service {action.estimated_service_delta:+.1%}, "
                f"risk {action.estimated_risk_delta:+.1%}, "
                f"cost {action.estimated_cost_delta:+,.0f}, "
                f"recovery time {action.estimated_recovery_hours:.0f}h."
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
                    f"superseded by {duplicate.action_id}, which addressed the same target with a stronger priority profile"
                )
            elif action.priority < threshold_priority:
                reason = (
                    f"lower operational priority ({action.priority:.2f}) than the chosen set threshold "
                    f"({threshold_priority:.2f}) under the plan action limit of {action_limit}"
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


def build_critic_review(
    selected_plan: Plan,
    evaluations: list[CandidatePlanEvaluation],
) -> tuple[str, list[str]]:
    selected = next(
        (item for item in evaluations if item.strategy_label == selected_plan.strategy_label),
        evaluations[0] if evaluations else None,
    )
    runner_up = None
    ordered = sorted(
        [item for item in evaluations if item.feasible] or evaluations,
        key=lambda item: item.score,
        reverse=True,
    )
    if ordered:
        for item in ordered:
            if item.strategy_label != selected_plan.strategy_label:
                runner_up = item
                break

    action_labels = ", ".join(_action_label(action) for action in selected_plan.actions[:3]) or "no-op coverage"
    summary = (
        f"Reviewer assessment: the {selected_plan.strategy_label or 'selected'} plan is reasonable because it uses "
        f"{action_labels} to support the current operating objective."
    )
    if selected is not None and runner_up is not None:
        summary += (
            f" It scored ahead of {runner_up.strategy_label} by {selected.score - runner_up.score:+.4f}, "
            f"mainly on service, cost, risk, and recovery trade-offs."
        )
    if selected_plan.approval_required:
        summary += " Human approval is prudent because the expected impact crosses the approval guardrail."

    findings: list[str] = []
    longest_recovery = max(
        (action.estimated_recovery_hours for action in selected_plan.actions),
        default=0.0,
    )
    if longest_recovery > 24:
        findings.append(
            f"The plan depends on at least one action with a recovery window of about {longest_recovery:.0f} hours, so benefits may arrive later than the first operating cycle."
        )
    if runner_up is not None and selected is not None:
        cost_gap = selected.projected_kpis.total_cost - runner_up.projected_kpis.total_cost
        service_gap = selected.projected_kpis.service_level - runner_up.projected_kpis.service_level
        risk_gap = selected.projected_kpis.disruption_risk - runner_up.projected_kpis.disruption_risk
        if cost_gap > 0:
            findings.append(
                f"Compared with {runner_up.strategy_label}, this plan carries {cost_gap:,.0f} more projected cost. Monitor whether the added spend is justified by the operating benefit."
            )
        if risk_gap >= 0:
            findings.append(
                f"Compared with {runner_up.strategy_label}, this plan does not materially lower projected disruption risk ({risk_gap:+.1%}). Monitor whether the recovery gain holds after execution."
            )
        elif service_gap < 0:
            findings.append(
                f"Compared with {runner_up.strategy_label}, this plan gives up {_pct(-service_gap)} of projected service level to gain resilience or cost control."
            )
    if selected_plan.approval_required and not findings:
        findings.append(
            "Approval is recommended because the plan changes the operating posture meaningfully enough to warrant human review."
        )
    if not findings:
        findings.append(
            "The plan is operationally sound, but the team should still confirm supplier, transport, and inventory execution milestones after release."
        )
    return summary, findings
