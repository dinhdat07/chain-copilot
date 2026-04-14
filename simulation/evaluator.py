from __future__ import annotations

from dataclasses import dataclass

from core.enums import EventType
from core.models import (
    Action,
    Event,
    KPIState,
    ProjectedStateSummary,
    ProjectionStep,
    SystemState,
)
from core.state import clone_state
from simulation.domain_rules import (
    SIMULATION_HORIZON_DAYS,
    SimulationContext,
    advance_demand,
    advance_inventory,
    advance_logistics,
    advance_risk,
    advance_supplier,
    apply_candidate_actions,
    dominant_constraint,
    initialize_context,
    step_summary,
)


@dataclass
class CandidateProjection:
    projected_state: SystemState
    projected_kpis: KPIState
    worst_case_kpis: KPIState
    projection_steps: list[ProjectionStep]
    projected_state_summary: ProjectedStateSummary
    projection_summary: str
    simulation_horizon_days: int = SIMULATION_HORIZON_DAYS


def evaluate_candidate_plan(
    *,
    state: SystemState,
    event: Event | None,
    actions: list[Action],
    horizon_days: int = SIMULATION_HORIZON_DAYS,
) -> CandidateProjection:
    projected_state = clone_state(state)
    projected_event = event.model_copy(deep=True) if event is not None else None
    if projected_event is not None and projected_state.active_events:
        projected_state.active_events[-1] = projected_event
    context = initialize_context(projected_state, projected_event)
    apply_candidate_actions(context, actions, event=projected_event)

    projection_steps: list[ProjectionStep] = []
    service_values: list[float] = [projected_state.kpis.service_level]
    cost_values: list[float] = [projected_state.kpis.total_cost]
    risk_values: list[float] = [projected_state.kpis.disruption_risk]
    stockout_values: list[float] = [projected_state.kpis.stockout_risk]
    final_metrics: dict[str, int] = {
        "inventory_at_risk": 0,
        "inventory_out_of_stock": 0,
        "backlog_units": 0,
        "inbound_units_due": 0,
    }

    for step_index in range(1, max(horizon_days, 1) + 1):
        advance_demand(context, step_index=step_index, event=projected_event)
        supplier_notes = advance_supplier(context, step_index=step_index, event=projected_event)
        route_notes = advance_logistics(context, step_index=step_index, event=projected_event)
        step_metrics = advance_inventory(context, step_index=step_index)
        final_metrics = step_metrics
        severity = advance_risk(context, event=projected_event, step_metrics=step_metrics)
        step_kpis = projected_state.kpis.model_copy(deep=True)
        service_values.append(step_kpis.service_level)
        cost_values.append(step_kpis.total_cost)
        risk_values.append(step_kpis.disruption_risk)
        stockout_values.append(step_kpis.stockout_risk)

        key_changes = supplier_notes[:2] + route_notes[:2]
        if step_metrics["inbound_units_due"] > 0:
            key_changes.append(f"{step_metrics['inbound_units_due']} units landed into the network")
        if step_metrics["backlog_units"] > 0:
            key_changes.append(f"backlog stands at {step_metrics['backlog_units']} units")

        projection_steps.append(
            ProjectionStep(
                step_index=step_index,
                label=f"T+{step_index}",
                kpis=step_kpis,
                event_severity=round(severity, 4),
                inventory_at_risk=step_metrics["inventory_at_risk"],
                inventory_out_of_stock=step_metrics["inventory_out_of_stock"],
                backlog_units=step_metrics["backlog_units"],
                inbound_units_due=step_metrics["inbound_units_due"],
                summary=step_summary(
                    context,
                    step_index=step_index,
                    step_metrics=step_metrics,
                    change_notes=key_changes,
                ),
                key_changes=key_changes[:4],
            )
        )

    projected_kpis = projected_state.kpis.model_copy(deep=True)
    worst_case_kpis = KPIState(
        service_level=round(min(service_values), 4),
        total_cost=round(max(cost_values), 2),
        disruption_risk=round(max(risk_values), 4),
        recovery_speed=projected_kpis.recovery_speed,
        stockout_risk=round(max(stockout_values), 4),
        decision_latency_ms=projected_kpis.decision_latency_ms,
    )
    summary = _projected_state_summary(
        context,
        final_metrics=final_metrics,
        projected_event=projected_event,
    )
    projection_summary = _projection_summary(
        projected_steps=projection_steps,
        projected_kpis=projected_kpis,
        worst_case_kpis=worst_case_kpis,
        summary=summary,
        event=projected_event,
    )
    return CandidateProjection(
        projected_state=projected_state,
        projected_kpis=projected_kpis,
        worst_case_kpis=worst_case_kpis,
        projection_steps=projection_steps,
        projected_state_summary=summary,
        projection_summary=projection_summary,
        simulation_horizon_days=max(horizon_days, 1),
    )


def _projected_state_summary(
    context: SimulationContext,
    *,
    final_metrics: dict[str, int],
    projected_event: Event | None,
) -> ProjectedStateSummary:
    total_scheduled = sum(
        max(int(qty), 0)
        for schedule in context.inbound_schedule.values()
        for qty in schedule.values()
    )
    constraint = dominant_constraint(context, final_metrics)
    event_severity_end = context.event_severity if projected_event is not None else 0.0
    summary = (
        f"By T+{SIMULATION_HORIZON_DAYS}, the network projects "
        f"{final_metrics['inventory_at_risk']} at-risk SKU(s), "
        f"{final_metrics['inventory_out_of_stock']} out-of-stock SKU(s), "
        f"and {final_metrics['backlog_units']} backlog units. "
        f"The dominant constraint is {constraint}."
    )
    return ProjectedStateSummary(
        inventory_at_risk=final_metrics["inventory_at_risk"],
        inventory_out_of_stock=final_metrics["inventory_out_of_stock"],
        backlog_units=final_metrics["backlog_units"],
        inbound_units_scheduled=total_scheduled,
        dominant_constraint=constraint,
        event_severity_end=round(event_severity_end, 4),
        summary=summary,
    )


def _projection_summary(
    *,
    projected_steps: list[ProjectionStep],
    projected_kpis: KPIState,
    worst_case_kpis: KPIState,
    summary: ProjectedStateSummary,
    event: Event | None,
) -> str:
    if not projected_steps:
        return "No forward projection was generated."
    worst_service_step = min(
        projected_steps,
        key=lambda item: item.kpis.service_level,
    )
    highest_risk_step = max(
        projected_steps,
        key=lambda item: item.kpis.disruption_risk,
    )
    event_text = ""
    if event is not None:
        if event.type == EventType.DEMAND_SPIKE:
            event_text = " Demand pressure is expected to normalize gradually."
        elif event.type in {EventType.SUPPLIER_DELAY, EventType.ROUTE_BLOCKAGE, EventType.COMPOUND}:
            event_text = " Mitigation quality determines whether disruption severity decays fast enough."
    return (
        f"Over the next {len(projected_steps)} day(s), service bottoms at "
        f"{worst_case_kpis.service_level:.0%} on {worst_service_step.label} while disruption risk peaks at "
        f"{worst_case_kpis.disruption_risk:.0%} on {highest_risk_step.label}. "
        f"By {projected_steps[-1].label}, the plan projects service at {projected_kpis.service_level:.0%}, "
        f"risk at {projected_kpis.disruption_risk:.0%}, and recovery speed at {projected_kpis.recovery_speed:.0%}. "
        f"{summary.summary}{event_text}"
    )

