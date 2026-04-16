from __future__ import annotations

from uuid import uuid4

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
    PlanMetadata
)
from core.logger import get_logger
from llm.service import enrich_plan_and_decision, generate_candidate_plan_drafts
from policies.explainability import (
    build_plan_summary,
    build_winning_factors,
    explain_rejected_actions,
)
from policies.constraints import evaluate_plan_constraints, mode_rationale, evaluate_hard_constraints, evaluate_soft_constraints
from policies.guardrails import approval_required
from policies.scoring import compute_score
from policies.strategic_prompt import (
    retrieve_relevant_cases,
    compute_memory_influence,
    derive_strategy_rationale,
    build_strategic_prompt,
)
from simulation.evaluator import evaluate_candidate_plan

logger = get_logger(__name__)


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
    ensured = list(candidate_actions)
    if any(action.action_type == ActionType.NO_OP for action in ensured):
        return ensured
    ensured.append(
        Action(
            action_id="act_no_op",
            action_type=ActionType.NO_OP,
            target_id="system",
            reason="no action required",
            priority=0.1,
        )
    )
    return ensured


def _drop_no_op_when_actions_exist(candidate_actions: list[Action]) -> list[Action]:
    real_actions = [
        action for action in candidate_actions if action.action_type != ActionType.NO_OP
    ]
    return real_actions if real_actions else candidate_actions


def _action_limit_for_mode(state: SystemState, candidate_count: int) -> int:
    del state
    # Do not hard-cap plan size; let strategy/feasibility logic decide action breadth.
    return max(candidate_count, 1)


def _inventory_pressure_summary(state: SystemState) -> dict[str, int]:
    critical = 0
    below_safety = 0
    for item in state.inventory.values():
        projected = item.on_hand + item.incoming_qty - item.forecast_qty
        if projected < item.reorder_point:
            critical += 1
        if projected < item.safety_stock:
            below_safety += 1
    return {
        "critical_skus": critical,
        "below_safety_stock": below_safety,
    }


def _should_suppress_no_op(state: SystemState) -> bool:
    pressure = _inventory_pressure_summary(state)
    return (
        state.kpis.service_level < 0.95
        or state.kpis.stockout_risk >= 0.05
        or pressure["critical_skus"] >= 8
        or pressure["below_safety_stock"] >= 2
    )


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


def _action_signature(action_ids: list[str]) -> tuple[str, ...]:
    return tuple(sorted({action_id for action_id in action_ids if action_id}))


def _build_distinct_repair_draft(
    *,
    strategy_label: str,
    candidate_actions: list[Action],
    action_limit: int,
    used_signatures: set[tuple[str, ...]],
) -> CandidatePlanDraft | None:
    ranked = sorted(
        candidate_actions,
        key=lambda action: _fallback_sort_key(strategy_label, action),
    )
    if not ranked:
        return None
    search_depth = min(len(ranked), max(action_limit * 4, 8))
    for offset in range(search_depth):
        rotated = ranked[offset:] + ranked[:offset]
        selected = _dedupe_actions(rotated, action_limit)
        signature = _action_signature([action.action_id for action in selected])
        if selected and signature not in used_signatures:
            return CandidatePlanDraft(
                strategy_label=strategy_label,
                action_ids=[action.action_id for action in selected],
                rationale=(
                    f"deterministic diversity repair applied to keep the {strategy_label} option "
                    "operationally distinct from other candidate plans"
                ),
                llm_used=False,
            )
    return None


def _enforce_distinct_drafts(
    drafts: list[CandidatePlanDraft],
    candidate_actions: list[Action],
    action_limit: int,
) -> tuple[list[CandidatePlanDraft], int]:
    distinct: list[CandidatePlanDraft] = []
    used_signatures: set[tuple[str, ...]] = set()
    repaired_count = 0
    for draft in drafts:
        signature = _action_signature(draft.action_ids)
        if signature and signature not in used_signatures:
            distinct.append(draft)
            used_signatures.add(signature)
            continue
        repaired = _build_distinct_repair_draft(
            strategy_label=draft.strategy_label,
            candidate_actions=candidate_actions,
            action_limit=action_limit,
            used_signatures=used_signatures,
        )
        if repaired is not None:
            distinct.append(repaired)
            used_signatures.add(_action_signature(repaired.action_ids))
            repaired_count += 1
        else:
            distinct.append(draft)
            if signature:
                used_signatures.add(signature)
    return distinct, repaired_count


def _inventory_gap_map(state: SystemState) -> dict[str, float]:
    gap_by_sku: dict[str, float] = {}
    for sku, item in state.inventory.items():
        projected = item.on_hand + item.incoming_qty - item.forecast_qty
        reorder_gap = max(float(item.reorder_point - projected), 0.0)
        if reorder_gap <= 0:
            continue
        safety_gap = max(float(item.safety_stock - projected), 0.0)
        gap_by_sku[sku] = reorder_gap + (safety_gap * 1.5)
    return gap_by_sku


def _coverage_metrics(
    evaluation: CandidatePlanEvaluation,
    *,
    gap_by_sku: dict[str, float],
    by_id: dict[str, Action],
) -> dict[str, float]:
    targeted_skus = {
        by_id[action_id].target_id
        for action_id in evaluation.action_ids
        if action_id in by_id and by_id[action_id].action_type != ActionType.NO_OP
    }
    covered_gap = sum(gap_by_sku.get(sku, 0.0) for sku in targeted_skus)
    total_gap = sum(gap_by_sku.values())
    coverage_fraction = (covered_gap / total_gap) if total_gap > 0 else 0.0
    critical_covered = sum(1 for sku in targeted_skus if sku in gap_by_sku)
    unresolved_critical = max(len(gap_by_sku) - critical_covered, 0)
    return {
        "coverage_fraction": coverage_fraction,
        "critical_covered": float(critical_covered),
        "unresolved_critical": float(unresolved_critical),
    }


def _decision_priority_score(
    evaluation: CandidatePlanEvaluation,
    *,
    gap_by_sku: dict[str, float],
    by_id: dict[str, Action],
    mode: str,
    state: SystemState,
) -> float:
    coverage = _coverage_metrics(evaluation, gap_by_sku=gap_by_sku, by_id=by_id)
    pressure = _inventory_pressure_summary(state)
    stressed_normal = (
        mode == "normal"
        and (
            state.kpis.stockout_risk >= 0.05
            or pressure["critical_skus"] >= 8
            or pressure["below_safety_stock"] >= 2
        )
    )
    coverage_weight = 0.016 if mode == "crisis" else (0.075 if stressed_normal else 0.012)
    unresolved_penalty = 0.0012 if mode == "crisis" else (0.0025 if stressed_normal else 0.0008)
    return round(
        evaluation.score
        + (coverage["coverage_fraction"] * coverage_weight)
        - (coverage["unresolved_critical"] * unresolved_penalty),
        6,
    )


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
    selected_mode_rationale = mode_rationale(state, event)
    violations = evaluate_plan_constraints(
        state=state,
        event=event,
        actions=actions,
    )
    feasible = not violations
    if not feasible:
        return CandidatePlanEvaluation(
            strategy_label=strategy_label,
            action_ids=[action.action_id for action in actions],
            score=0.0,
            score_breakdown={
                "service_level": 0.0,
                "total_cost": 0.0,
                "disruption_risk": 0.0,
                "recovery_speed": 0.0,
            },
            projected_kpis=before_kpis.model_copy(deep=True),
            worst_case_kpis=before_kpis.model_copy(deep=True),
            simulation_horizon_days=0,
            projection_steps=[],
            projected_state_summary=None,
            projection_summary="candidate was not simulated because hard constraints failed",
            feasible=False,
            violations=violations,
            mode_rationale=selected_mode_rationale,
            approval_required=False,
            approval_reason="not evaluated because the candidate plan is infeasible",
            rationale=rationale,
            llm_used=llm_used,
        )
    projection = evaluate_candidate_plan(
        state=state,
        event=event,
        actions=actions,
    )
    score, breakdown = compute_score(
        service_level=projection.worst_case_kpis.service_level,
        total_cost=projection.projected_kpis.total_cost,
        disruption_risk=projection.worst_case_kpis.disruption_risk,
        recovery_speed=projection.projected_kpis.recovery_speed,
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
    needs_approval, reason = approval_required(
        transient_plan,
        before_kpis,
        projection.projected_kpis,
        event,
    )
    return CandidatePlanEvaluation(
        strategy_label=strategy_label,
        action_ids=[action.action_id for action in actions],
        score=score,
        score_breakdown=breakdown,
        projected_kpis=projection.projected_kpis,
        worst_case_kpis=projection.worst_case_kpis,
        simulation_horizon_days=projection.simulation_horizon_days,
        projection_steps=projection.projection_steps,
        projected_state_summary=projection.projected_state_summary,
        projection_summary=projection.projection_summary,
        feasible=True,
        violations=[],
        mode_rationale=selected_mode_rationale,
        approval_required=needs_approval,
        approval_reason=reason if needs_approval else "no approval required: thresholds not triggered",
        rationale=rationale,
        llm_used=llm_used,
    )


def _adaptive_scope_bounds(
    *,
    state: SystemState,
    event: Event | None,
    available_actions: int,
) -> tuple[int, int]:
    if available_actions <= 0:
        return 0, 0
    min_actions = 1
    if state.mode.value == "crisis" and available_actions >= 2:
        min_actions = 2
    if event is None and _should_suppress_no_op(state) and available_actions >= 2:
        min_actions = max(min_actions, 2)
    return min_actions, available_actions


def _action_count_penalty(
    *,
    action_count: int,
    state: SystemState,
    event: Event | None,
) -> float:
    if action_count <= 1:
        return 0.0
    if state.mode.value == "crisis":
        return (action_count - 1) * 0.00008
    if event is not None:
        return (action_count - 1) * 0.00012
    return (action_count - 1) * 0.00025


def _target_coverage_fraction(
    *,
    state: SystemState,
    event: Event | None,
    gap_by_sku: dict[str, float],
) -> float:
    if not gap_by_sku:
        return 0.0
    pressure = _inventory_pressure_summary(state)
    if state.mode.value == "crisis":
        if event is not None and event.severity >= 0.85:
            return 0.95
        if event is not None and event.severity >= 0.65:
            return 0.90
        return 0.80
    if pressure["critical_skus"] >= 20:
        return 0.75
    if pressure["critical_skus"] >= 12:
        return 0.65
    if pressure["critical_skus"] >= 8:
        return 0.55
    return 0.40


def _coverage_approval_guardrail(
    *,
    selected: CandidatePlanEvaluation,
    state: SystemState,
    event: Event | None,
    gap_by_sku: dict[str, float],
) -> tuple[bool, str]:
    if event is None:
        return False, ""
    if not gap_by_sku:
        return False, ""

    target_coverage = _target_coverage_fraction(
        state=state,
        event=event,
        gap_by_sku=gap_by_sku,
    )
    crisis_floor = max(target_coverage - 0.05, 0.60)

    if event.severity >= 0.65 and selected.unresolved_critical > 0:
        return (
            True,
            (
                f"selected plan leaves {selected.unresolved_critical} critical SKU(s) unresolved "
                f"under disruption severity {event.severity:.2f}"
            ),
        )
    if state.mode.value == "crisis" and selected.coverage_fraction < crisis_floor:
        return (
            True,
            (
                f"selected plan covers {selected.coverage_fraction:.0%} of critical exposure, "
                f"below the crisis guardrail floor ({crisis_floor:.0%})"
            ),
        )
    return False, ""


def _expand_selected_for_coverage(
    *,
    selected: CandidatePlanEvaluation,
    state: SystemState,
    event: Event | None,
    before_kpis,
    by_id: dict[str, Action],
    gap_by_sku: dict[str, float],
) -> CandidatePlanEvaluation:
    if event is None or event.severity < 0.65:
        return selected
    if not gap_by_sku or selected.unresolved_critical <= 0:
        return selected

    target_coverage = _target_coverage_fraction(
        state=state,
        event=event,
        gap_by_sku=gap_by_sku,
    )
    max_unresolved = max(int(len(gap_by_sku) * (1.0 - target_coverage)), 0)

    selected_action_ids = [action_id for action_id in selected.action_ids if action_id in by_id]
    selected_actions = [by_id[action_id] for action_id in selected_action_ids]
    selected_targeted = {
        action.target_id
        for action in selected_actions
        if action.action_type != ActionType.NO_OP
    }
    total_gap = sum(gap_by_sku.values()) or 1.0
    selected_covered_gap = sum(gap_by_sku.get(sku, 0.0) for sku in selected_targeted)
    selected_coverage = selected_covered_gap / total_gap
    selected_unresolved = max(len(gap_by_sku) - len(selected_targeted & set(gap_by_sku)), 0)
    if selected_coverage >= target_coverage and selected_unresolved <= max_unresolved:
        return selected

    additional_actions = [
        action
        for action in by_id.values()
        if action.action_id not in selected_action_ids
        and action.action_type != ActionType.NO_OP
        and action.target_id in gap_by_sku
    ]
    additional_actions.sort(
        key=lambda action: (
            gap_by_sku.get(action.target_id, 0.0),
            action.priority,
            -action.estimated_risk_delta,
            action.estimated_service_delta,
        ),
        reverse=True,
    )

    expanded_action_ids = list(selected_action_ids)
    expanded_actions = list(selected_actions)
    targeted = set(selected_targeted)
    covered_gap = selected_covered_gap

    for action in additional_actions:
        expanded_action_ids.append(action.action_id)
        expanded_actions.append(action)
        if action.target_id not in targeted:
            targeted.add(action.target_id)
            covered_gap += gap_by_sku.get(action.target_id, 0.0)
        coverage_fraction = covered_gap / total_gap
        unresolved = max(len(gap_by_sku) - len(targeted & set(gap_by_sku)), 0)
        if coverage_fraction >= target_coverage and unresolved <= max_unresolved:
            break

    if len(expanded_action_ids) == len(selected_action_ids):
        return selected

    expanded_evaluation = _evaluate_candidate(
        state=state,
        event=event,
        before_kpis=before_kpis,
        strategy_label=selected.strategy_label,
        actions=expanded_actions,
        rationale=selected.rationale,
        llm_used=selected.llm_used,
    )
    if not expanded_evaluation.feasible:
        return selected

    expanded_coverage = _coverage_metrics(
        expanded_evaluation,
        gap_by_sku=gap_by_sku,
        by_id=by_id,
    )
    expanded_evaluation.coverage_fraction = round(expanded_coverage["coverage_fraction"], 4)
    expanded_evaluation.critical_covered = int(expanded_coverage["critical_covered"])
    expanded_evaluation.unresolved_critical = int(expanded_coverage["unresolved_critical"])

    if (
        expanded_evaluation.unresolved_critical < selected.unresolved_critical
        or expanded_evaluation.coverage_fraction > selected.coverage_fraction
    ):
        expanded_evaluation.approval_required = True
        expanded_evaluation.approval_reason = (
            "coverage guardrail expanded the selected strategy to reduce unresolved critical SKUs"
        )
        return expanded_evaluation
    return selected


def _optimize_draft_scope(
    *,
    draft: CandidatePlanDraft,
    by_id: dict[str, Action],
    state: SystemState,
    event: Event | None,
    before_kpis,
    gap_by_sku: dict[str, float],
) -> CandidatePlanEvaluation:
    ordered_actions = [by_id[action_id] for action_id in draft.action_ids if action_id in by_id]
    min_actions, max_actions = _adaptive_scope_bounds(
        state=state,
        event=event,
        available_actions=len(ordered_actions),
    )
    if max_actions == 0:
        return _evaluate_candidate(
            state=state,
            event=event,
            before_kpis=before_kpis,
            strategy_label=draft.strategy_label,
            actions=[],
            rationale=draft.rationale,
            llm_used=draft.llm_used,
        )

    best_evaluation: CandidatePlanEvaluation | None = None
    best_adjusted = float("-inf")
    best_priority = float("-inf")
    candidates: list[tuple[CandidatePlanEvaluation, float, float]] = []
    for action_count in range(min_actions, max_actions + 1):
        evaluation = _evaluate_candidate(
            state=state,
            event=event,
            before_kpis=before_kpis,
            strategy_label=draft.strategy_label,
            actions=ordered_actions[:action_count],
            rationale=draft.rationale,
            llm_used=draft.llm_used,
        )
        priority_score = _decision_priority_score(
            evaluation,
            gap_by_sku=gap_by_sku,
            by_id=by_id,
            mode=state.mode.value,
            state=state,
        )
        adjusted_score = priority_score - _action_count_penalty(
            action_count=action_count,
            state=state,
            event=event,
        )
        coverage = _coverage_metrics(
            evaluation,
            gap_by_sku=gap_by_sku,
            by_id=by_id,
        )
        candidates.append((evaluation, adjusted_score, coverage["coverage_fraction"]))
        if (
            adjusted_score > best_adjusted
            or (
                adjusted_score == best_adjusted
                and (
                    priority_score > best_priority
                    or (
                        priority_score == best_priority
                        and best_evaluation is not None
                        and len(evaluation.action_ids) < len(best_evaluation.action_ids)
                    )
                )
            )
        ):
            best_adjusted = adjusted_score
            best_priority = priority_score
            best_evaluation = evaluation

    target_coverage = _target_coverage_fraction(
        state=state,
        event=event,
        gap_by_sku=gap_by_sku,
    )
    if candidates and target_coverage > 0.0:
        near_best_threshold = best_adjusted - 0.035
        eligible = [
            (evaluation, adjusted_score, coverage)
            for evaluation, adjusted_score, coverage in candidates
            if coverage >= target_coverage and adjusted_score >= near_best_threshold
        ]
        if eligible:
            eligible.sort(
                key=lambda item: (
                    len(item[0].action_ids),
                    -item[1],
                    -item[2],
                )
            )
            best_evaluation = eligible[0][0]

    assert best_evaluation is not None
    return best_evaluation


def _select_best_evaluation(
    evaluations: list[CandidatePlanEvaluation],
    *,
    state: SystemState,
    by_id: dict[str, Action],
) -> CandidatePlanEvaluation:
    feasible_evaluations = [item for item in evaluations if item.feasible]
    pool = feasible_evaluations or evaluations
    gap_by_sku = _inventory_gap_map(state)
    return max(
        pool,
        key=lambda item: (
            _decision_priority_score(
                item,
                gap_by_sku=gap_by_sku,
                by_id=by_id,
                mode=state.mode.value,
                state=state,
            ),
            item.score,
            -item.projected_kpis.disruption_risk,
            item.projected_kpis.service_level,
            -item.projected_kpis.total_cost,
            1 if item.strategy_label == "balanced" else 0,
        ),
    )


def _selection_reason(
    selected: CandidatePlanEvaluation,
    evaluations: list[CandidatePlanEvaluation],
    *,
    state: SystemState,
    by_id: dict[str, Action],
) -> str:
    infeasible_count = sum(1 for item in evaluations if not item.feasible)
    gap_by_sku = _inventory_gap_map(state)
    selected_priority_score = _decision_priority_score(
        selected,
        gap_by_sku=gap_by_sku,
        by_id=by_id,
        mode=state.mode.value,
        state=state,
    )
    ordered = sorted(
        [item for item in evaluations if item.feasible] or evaluations,
        key=lambda item: (
            _decision_priority_score(
                item,
                gap_by_sku=gap_by_sku,
                by_id=by_id,
                mode=state.mode.value,
                state=state,
            ),
            item.score,
            -item.projected_kpis.disruption_risk,
            item.projected_kpis.service_level,
            -item.projected_kpis.total_cost,
        ),
        reverse=True,
    )
    runner_up = ordered[1] if len(ordered) > 1 else None
    base = (
        f"Selected {selected.strategy_label} as the lead recommendation because it produced the strongest overall priority score "
        f"({selected_priority_score:.4f})"
    )
    if infeasible_count:
        base = f"{base} after excluding {infeasible_count} infeasible candidate plan(s)"
    if runner_up is None:
        return base
    runner_up_priority_score = _decision_priority_score(
        runner_up,
        gap_by_sku=gap_by_sku,
        by_id=by_id,
        mode=state.mode.value,
        state=state,
    )
    selected_coverage = _coverage_metrics(selected, gap_by_sku=gap_by_sku, by_id=by_id)
    runner_up_coverage = _coverage_metrics(
        runner_up,
        gap_by_sku=gap_by_sku,
        by_id=by_id,
    )
    coverage_note = ""
    if selected_coverage["critical_covered"] > runner_up_coverage["critical_covered"]:
        coverage_note = (
            f" It also covered more at-risk SKUs ({int(selected_coverage['critical_covered'])} vs "
            f"{int(runner_up_coverage['critical_covered'])})."
        )
    elif selected_coverage["coverage_fraction"] > runner_up_coverage["coverage_fraction"]:
        coverage_note = " It addressed a larger share of current inventory exposure."
    return (
        f"{base}. It ranked ahead of {runner_up.strategy_label} ({runner_up_priority_score:.4f}) after comparing "
        f"service protection, cost, disruption risk, and recovery speed.{coverage_note}"
    )


def _safe_hold_evaluation(
    *,
    state: SystemState,
    event: Event | None,
    before_kpis,
    safe_action: Action,
    infeasible_count: int,
) -> CandidatePlanEvaluation:
    score, breakdown = compute_score(
        service_level=before_kpis.service_level,
        total_cost=before_kpis.total_cost,
        disruption_risk=before_kpis.disruption_risk,
        recovery_speed=before_kpis.recovery_speed,
        mode=state.mode,
        baseline_cost=before_kpis.total_cost,
    )
    return CandidatePlanEvaluation(
        strategy_label="safe_hold",
        action_ids=[safe_action.action_id],
        score=score,
        score_breakdown=breakdown,
        projected_kpis=before_kpis.model_copy(deep=True),
        worst_case_kpis=before_kpis.model_copy(deep=True),
        simulation_horizon_days=0,
        projection_steps=[],
        projected_state_summary=None,
        projection_summary="the system retained the current network position because no feasible candidate plan was available",
        feasible=True,
        violations=[],
        mode_rationale=mode_rationale(state, event),
        approval_required=False,
        approval_reason="no approval required: retaining current state because all candidate plans were infeasible",
        rationale=(
            f"no candidate plan satisfied hard constraints; retaining the current network state after excluding "
            f"{infeasible_count} infeasible candidate plan(s)"
        ),
        llm_used=False,
    )


class PlannerAgent(BaseAgent):
    name = "planner"

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        
        candidate_actions = _ensure_actions(state.candidate_actions)
        if event is not None:
            candidate_actions = _drop_no_op_when_actions_exist(candidate_actions)
        suppress_no_op = event is None and _should_suppress_no_op(state)
        if suppress_no_op:
            candidate_actions = _drop_no_op_when_actions_exist(candidate_actions)

        feasible_candidates = []
        infeasible_reasons = {}
        for act in candidate_actions:
            dummy_plan = Plan(plan_id="tmp", mode=state.mode, score=0, score_breakdown={}, actions=[act])
            is_feas, vios = evaluate_hard_constraints(dummy_plan, state)
            if is_feas:
                feasible_candidates.append(act)
            else:
                infeasible_reasons[act.action_id] = vios
                
        if not feasible_candidates and candidate_actions:
            feasible_candidates = [
                Action(
                    action_id="act_no_op_fallback", action_type=ActionType.NO_OP, target_id="system", 
                    reason="all candidate actions violated hard constraints", priority=0.0
                )
            ]
        action_limit = _action_limit_for_mode(state, len(feasible_candidates))

        effective_event = event or (state.active_events[-1] if state.active_events else None)
        historical_cases = retrieve_relevant_cases(effective_event, state.memory, top_k=3)
        memory_influence = compute_memory_influence(historical_cases)
        strategic_prompt = build_strategic_prompt(
            mode=state.mode.value, event=effective_event, 
            historical_cases=historical_cases, candidate_actions=feasible_candidates
        )

        before_kpis = state.kpis.model_copy(deep=True)
        llm_drafts, planner_error = generate_candidate_plan_drafts(
            state=state, event=event, candidate_actions=feasible_candidates
        )
        logger.info(
            "planner candidate generation result llm_drafts=%s planner_error=%s feasible_candidates=%s suppress_no_op=%s action_limit=%s",
            len(llm_drafts),
            planner_error or "none",
            len(feasible_candidates),
            suppress_no_op,
            action_limit,
        )
        
        if planner_error == "llm_disabled":
            drafts = _fallback_drafts(feasible_candidates, action_limit)
            repaired_count = 0
            fallback_used = False
            logger.info(
                "planner deterministic path used because llm is disabled action_limit=%s",
                action_limit,
            )
        else:
            drafts, repaired_count = _normalize_drafts(llm_drafts, feasible_candidates, action_limit)
            drafts, duplicate_repair_count = _enforce_distinct_drafts(
                drafts,
                feasible_candidates,
                action_limit,
            )
            repaired_count += duplicate_repair_count
            fallback_used = repaired_count > 0
            if fallback_used and not planner_error:
                planner_error = "planner returned duplicate, incomplete, or invalid candidate plans"
            if fallback_used:
                logger.warning(
                    "planner fallback activated repaired_count=%s total_strategies=%s reason=%s",
                    repaired_count,
                    len(STRATEGY_ORDER),
                    planner_error or "unknown_reason",
                )
            else:
                logger.info("planner used llm candidate drafts without repair")

        by_id = {action.action_id: action for action in feasible_candidates}
        gap_by_sku = _inventory_gap_map(state)
        evaluations: list[CandidatePlanEvaluation] = []
        for draft in drafts:
            evaluations.append(
                _optimize_draft_scope(
                    draft=draft,
                    by_id=by_id,
                    state=state,
                    event=event,
                    before_kpis=before_kpis,
                    gap_by_sku=gap_by_sku,
                )
            )

        for evaluation in evaluations:
            coverage = _coverage_metrics(
                evaluation,
                gap_by_sku=gap_by_sku,
                by_id=by_id,
            )
            evaluation.coverage_fraction = round(coverage["coverage_fraction"], 4)
            evaluation.critical_covered = int(coverage["critical_covered"])
            evaluation.unresolved_critical = int(coverage["unresolved_critical"])

        if not any(item.feasible for item in evaluations):
            safe_action = next((action for action in feasible_candidates if action.action_type == ActionType.NO_OP), Action(action_id="act_no_op_fallback", action_type=ActionType.NO_OP, target_id="system", reason="all candidate actions violated hard constraints", priority=0.0))
            evaluations.append(
                _safe_hold_evaluation(
                    state=state, event=event, before_kpis=before_kpis,
                    safe_action=safe_action, infeasible_count=len(evaluations),
                )
            )


        selected_evaluation = _select_best_evaluation(
            evaluations,
            state=state,
            by_id=by_id,
        )
        guardrail_event = event or (state.active_events[-1] if state.active_events else None)
        selected_evaluation = _expand_selected_for_coverage(
            selected=selected_evaluation,
            state=state,
            event=guardrail_event,
            before_kpis=before_kpis,
            by_id=by_id,
            gap_by_sku=gap_by_sku,
        )
        selected_actions = [by_id[action_id] for action_id in selected_evaluation.action_ids if action_id in by_id]
        requires_manual_review, manual_review_reason = _coverage_approval_guardrail(
            selected=selected_evaluation,
            state=state,
            event=guardrail_event,
            gap_by_sku=gap_by_sku,
        )
        if requires_manual_review:
            selected_evaluation.approval_required = True
            prior_reason = (selected_evaluation.approval_reason or "").strip()
            if not prior_reason or prior_reason.startswith("no approval required"):
                selected_evaluation.approval_reason = manual_review_reason
            elif manual_review_reason not in prior_reason:
                selected_evaluation.approval_reason = (
                    f"{prior_reason}; {manual_review_reason}"
                )
        
        ordered_evaluations = sorted(
            [item for item in evaluations if item.feasible] or evaluations,
            key=lambda item: (
                item.score,
                -item.projected_kpis.disruption_risk,
                item.projected_kpis.service_level,
                -item.projected_kpis.total_cost,
            ),
            reverse=True,
        )
        runner_up = next(
            (item for item in ordered_evaluations if item.strategy_label != selected_evaluation.strategy_label),
            None,
        )
        summary = build_plan_summary(
            before_kpis,
            selected_evaluation.projected_kpis,
            selected_evaluation.score_breakdown,
            selected_actions=selected_actions,
            strategy_label=selected_evaluation.strategy_label,
            mode=state.mode,
            runner_up=runner_up,
            mode_rationale=selected_evaluation.mode_rationale,
            projection_summary=selected_evaluation.projection_summary,
            simulation_horizon_days=selected_evaluation.simulation_horizon_days,
            worst_case_kpis=selected_evaluation.worst_case_kpis,
        )

        final_plan = Plan(
            plan_id=f"plan_{uuid4().hex[:8]}",
            mode=state.mode,
            trigger_event_ids=[event.event_id] if event else [],
            actions=selected_actions,
            score=selected_evaluation.score,
            score_breakdown=selected_evaluation.score_breakdown,
            feasible=selected_evaluation.feasible,
            violations=selected_evaluation.violations,
            mode_rationale=selected_evaluation.mode_rationale,
            strategy_label=selected_evaluation.strategy_label,
            generated_by=(
                "deterministic_planner"
                if planner_error == "llm_disabled"
                else (
                    "llm_planner"
                    if repaired_count == 0
                    else ("llm_planner_repaired" if repaired_count < len(STRATEGY_ORDER) else "hybrid_fallback")
                )
            ),
            approval_required=selected_evaluation.approval_required,
            approval_reason=selected_evaluation.approval_reason if selected_evaluation.approval_required else "",
            planner_reasoning=summary,
            status=PlanStatus.PROPOSED,
        )

        is_hard_feas, hard_violations = evaluate_hard_constraints(final_plan, state)
        soft_violations = evaluate_soft_constraints(final_plan, state)

        final_plan.feasible = is_hard_feas
        final_plan.violations = hard_violations + soft_violations


        strategy_rationale = derive_strategy_rationale(effective_event, historical_cases, selected_actions)
        final_plan.metadata = PlanMetadata(
            referenced_cases=historical_cases,
            memory_influence_score=memory_influence,
            strategy_rationale=strategy_rationale,
            strategic_prompt=strategic_prompt
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
            plan_id=final_plan.plan_id,
            event_ids=final_plan.trigger_event_ids,
            before_kpis=before_kpis,
            after_kpis=selected_evaluation.projected_kpis,
            selected_actions=[action.action_id for action in selected_actions],
            rejected_actions=rejection_reasons,
            score_breakdown=selected_evaluation.score_breakdown,
            mode_rationale=selected_evaluation.mode_rationale,
            rationale=summary,
            candidate_evaluations=evaluations,
            selection_reason=_selection_reason(
                selected_evaluation,
                evaluations,
                state=state,
                by_id=by_id,
            ),
            winning_factors=winning_factors,
            approval_required=selected_evaluation.approval_required,
            approval_reason=selected_evaluation.approval_reason,
            approval_status=ApprovalStatus.PENDING if selected_evaluation.approval_required else ApprovalStatus.AUTO_APPLIED,
            planner_error=planner_error if fallback_used else None,
            metadata=final_plan.metadata, 
        )
        
        enrich_plan_and_decision(state=state, event=event, plan=final_plan, decision_log=decision_log)

        state.latest_plan = final_plan
        state.latest_plan_id = final_plan.plan_id
        state.pending_plan = final_plan if final_plan.approval_required else None
        state.decision_logs.append(decision_log)
        
        proposal.observations.append(
            f"built {final_plan.plan_id} using {final_plan.strategy_label} with score {final_plan.score:.4f}"
        )
        if fallback_used and planner_error:
            proposal.risks.append(
                f"planner {'repair' if repaired_count < len(STRATEGY_ORDER) else 'fallback'} used: {planner_error}"
            )
        proposal.domain_summary = final_plan.llm_planner_narrative or final_plan.planner_reasoning
        proposal.notes_for_planner = decision_log.selection_reason
        proposal.downstream_impacts = winning_factors[:3]
        if runner_up is not None:
            proposal.tradeoffs.append(
                f"The chosen plan beat {runner_up.strategy_label} by trading off service, cost, risk, and recovery priorities more effectively for the current mode."
            )
        if suppress_no_op:
            proposal.observations.append(
                "Planner suppressed the no-action option because current inventory stress already exceeds the normal operating tolerance."
            )
        proposal.llm_used = any(evaluation.llm_used for evaluation in evaluations)
        proposal.llm_error = planner_error if (fallback_used and planner_error != "llm_disabled") else None
        logger.info(
            "planner final selection strategy=%s generated_by=%s llm_used=%s llm_error=%s",
            final_plan.strategy_label,
            final_plan.generated_by,
            proposal.llm_used,
            proposal.llm_error or "none",
        )
        
        return proposal
