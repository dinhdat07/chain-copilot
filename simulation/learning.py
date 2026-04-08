from __future__ import annotations

from core.enums import ApprovalStatus, EventType
from core.models import MemorySnapshot, ScenarioRun, SystemState
from core.state import default_memory, utc_now


def _bounded(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _update_supplier_learning(state: SystemState, supplier_id: str, severity: float) -> float | None:
    if supplier_id not in state.suppliers:
        return None
    memory = state.memory or default_memory()
    current = memory.supplier_reliability.get(supplier_id, state.suppliers[supplier_id].reliability)
    updated = _bounded(current - (0.06 * severity))
    memory.supplier_reliability[supplier_id] = updated
    state.suppliers[supplier_id].reliability = updated
    state.memory = memory
    return updated


def _update_route_learning(state: SystemState, route_id: str, severity: float) -> float | None:
    if route_id not in state.routes:
        return None
    memory = state.memory or default_memory()
    current = memory.route_disruption_priors.get(route_id, state.routes[route_id].risk_score)
    updated = _bounded(current + (0.08 * severity))
    memory.route_disruption_priors[route_id] = updated
    state.routes[route_id].risk_score = updated
    state.memory = memory
    return updated


def apply_learning(state: SystemState, run: ScenarioRun) -> None:
    memory = state.memory or default_memory()
    supplier_updates: dict[str, float] = {}
    route_updates: dict[str, float] = {}

    for event in run.events:
        supplier_id = event.payload.get("supplier_id")
        route_id = event.payload.get("route_id")
        if supplier_id and event.type in {EventType.SUPPLIER_DELAY, EventType.COMPOUND}:
            updated_supplier = _update_supplier_learning(state, supplier_id, event.severity)
            if updated_supplier is not None:
                supplier_updates[supplier_id] = updated_supplier
        if route_id and event.type in {EventType.ROUTE_BLOCKAGE, EventType.COMPOUND}:
            updated_route = _update_route_learning(state, route_id, event.severity)
            if updated_route is not None:
                route_updates[route_id] = updated_route

    latest_decision = state.decision_logs[-1] if state.decision_logs else None
    outcome_summary = {
        "run_id": run.run_id,
        "scenario_id": run.scenario_id,
        "event_types": [event.type.value for event in run.events],
        "plan_id": run.result_plan_id,
        "mode": state.mode.value,
        "approval_status": (
            latest_decision.approval_status.value if latest_decision else ApprovalStatus.NOT_REQUIRED.value
        ),
        "service_level": state.kpis.service_level,
        "total_cost": state.kpis.total_cost,
        "disruption_risk": state.kpis.disruption_risk,
        "recovery_speed": state.kpis.recovery_speed,
        "supplier_updates": supplier_updates,
        "route_updates": route_updates,
    }
    run.outcome_summary = outcome_summary

    scenario_state = memory.scenario_outcomes.get(
        run.scenario_id,
        {"runs": 0, "history": []},
    )
    history = list(scenario_state.get("history", []))
    history.append(outcome_summary)
    scenario_state.update(
        {
            "runs": int(scenario_state.get("runs", 0)) + 1,
            "latest_run_id": run.run_id,
            "latest_plan_id": run.result_plan_id,
            "latest_kpis": state.kpis.model_dump(mode="json"),
            "latest_approval_status": outcome_summary["approval_status"],
            "history": history,
        }
    )
    memory.scenario_outcomes[run.scenario_id] = scenario_state
    memory.snapshot_id = f"mem_{len(state.scenario_history) + 1}"
    memory.timestamp = utc_now()
    if latest_decision and latest_decision.approval_status in {
        ApprovalStatus.APPROVED,
        ApprovalStatus.AUTO_APPLIED,
    } and run.result_plan_id:
        memory.last_approved_plan_ids.append(run.result_plan_id)
    state.memory = MemorySnapshot.model_validate(memory.model_dump())
