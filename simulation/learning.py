from __future__ import annotations

from uuid import uuid4

from core.enums import ApprovalStatus, EventType
from core.models import DecisionLog, MemorySnapshot, ReflectionNote, ScenarioRun, SystemState
from core.state import default_memory, utc_now
from llm.service import generate_reflection_note


FINAL_APPROVAL_STATUSES = {
    ApprovalStatus.APPROVED.value,
    ApprovalStatus.AUTO_APPLIED.value,
}


def _bounded(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _latest_decision(state: SystemState) -> DecisionLog | None:
    return state.decision_logs[-1] if state.decision_logs else None


def _latest_run(state: SystemState) -> ScenarioRun | None:
    return state.scenario_history[-1] if state.scenario_history else None


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


def _update_numeric_learning(state: SystemState, run: ScenarioRun) -> tuple[dict[str, float], dict[str, float]]:
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
    return supplier_updates, route_updates


def _build_outcome_summary(
    state: SystemState,
    run: ScenarioRun,
    latest_decision: DecisionLog | None,
    supplier_updates: dict[str, float],
    route_updates: dict[str, float],
) -> dict:
    approval_status = (
        latest_decision.approval_status.value if latest_decision else ApprovalStatus.NOT_REQUIRED.value
    )
    return {
        "run_id": run.run_id,
        "scenario_id": run.scenario_id,
        "event_types": [event.type.value for event in run.events],
        "plan_id": run.result_plan_id,
        "decision_id": run.decision_id,
        "mode": state.mode.value,
        "approval_status": approval_status,
        "service_level": state.kpis.service_level,
        "total_cost": state.kpis.total_cost,
        "disruption_risk": state.kpis.disruption_risk,
        "recovery_speed": state.kpis.recovery_speed,
        "supplier_updates": supplier_updates,
        "route_updates": route_updates,
        "reflection_status": run.reflection_status,
        "reflection_note_id": run.reflection_note_id,
    }


def _upsert_history(history: list[dict], outcome_summary: dict) -> list[dict]:
    updated = list(history)
    for index, item in enumerate(updated):
        if item.get("run_id") == outcome_summary["run_id"]:
            updated[index] = outcome_summary
            return updated
    updated.append(outcome_summary)
    return updated


def _save_outcome_summary(state: SystemState, run: ScenarioRun) -> None:
    memory = state.memory or default_memory()
    scenario_state = memory.scenario_outcomes.get(
        run.scenario_id,
        {"runs": 0, "history": []},
    )
    history = _upsert_history(list(scenario_state.get("history", [])), run.outcome_summary)
    previous_runs = int(scenario_state.get("runs", 0))
    run_seen = any(item.get("run_id") == run.run_id for item in scenario_state.get("history", []))
    scenario_state.update(
        {
            "runs": previous_runs if run_seen else previous_runs + 1,
            "latest_run_id": run.run_id,
            "latest_plan_id": run.result_plan_id,
            "latest_kpis": state.kpis.model_dump(mode="json"),
            "latest_approval_status": run.approval_status,
            "latest_reflection_status": run.reflection_status,
            "history": history,
        }
    )
    memory.scenario_outcomes[run.scenario_id] = scenario_state
    memory.snapshot_id = f"mem_{len(state.scenario_history) + 1}"
    memory.timestamp = utc_now()
    state.memory = MemorySnapshot.model_validate(memory.model_dump())


def _deterministic_reflection_note(
    state: SystemState,
    run: ScenarioRun,
    decision_log: DecisionLog | None,
    error: str | None = None,
) -> ReflectionNote:
    event_types = [event.type.value for event in run.events]
    primary_event = event_types[0] if event_types else "unknown"
    selected_actions = decision_log.selected_actions if decision_log else []
    lessons = [
        f"{primary_event} required close monitoring of supplier, route, and service trade-offs.",
        (
            f"chosen plan used {', '.join(selected_actions[:2])}"
            if selected_actions
            else "no executable plan was selected at reflection time"
        ),
    ]
    tags = sorted(
        {
            primary_event,
            state.mode.value,
            "approval_required" if run.approval_status in FINAL_APPROVAL_STATUSES else "approval_pending",
        }
    )
    checks = [
        "review supplier reliability and route risk priors before the next run",
        "compare the selected strategy against the next disruption of the same type",
    ]
    return ReflectionNote(
        note_id=f"note_{uuid4().hex[:8]}",
        run_id=run.run_id,
        scenario_id=run.scenario_id,
        plan_id=run.result_plan_id,
        event_types=event_types,
        mode=state.mode.value,
        approval_status=run.approval_status or ApprovalStatus.NOT_REQUIRED.value,
        summary=(
            f"Scenario {run.scenario_id} finished in {state.mode.value} mode after {primary_event}; "
            f"service level settled at {state.kpis.service_level:.2f} with total cost {state.kpis.total_cost:.2f}."
        ),
        lessons=lessons,
        pattern_tags=tags,
        follow_up_checks=checks,
        llm_used=False,
        llm_error=error,
    )


def _store_reflection(memory: MemorySnapshot, note: ReflectionNote) -> None:
    notes = [item for item in memory.reflection_notes if item.note_id != note.note_id]
    notes.append(note)
    memory.reflection_notes = notes
    counts: dict[str, int] = {}
    for item in memory.reflection_notes:
        for tag in item.pattern_tags:
            counts[tag] = counts.get(tag, 0) + 1
    memory.pattern_tag_counts = counts


def _finalize_reflection_note(state: SystemState, run: ScenarioRun) -> ReflectionNote | None:
    decision_log = _latest_decision(state)
    if run.approval_status not in FINAL_APPROVAL_STATUSES:
        return None
    note, error = generate_reflection_note(
        state=state,
        run=run,
        decision_log=decision_log,
    )
    if note is None:
        note = _deterministic_reflection_note(state, run, decision_log, error)
    memory = state.memory or default_memory()
    _store_reflection(memory, note)
    state.memory = MemorySnapshot.model_validate(memory.model_dump())
    run.reflection_note_id = note.note_id
    run.reflection_status = "completed"
    return note


def _mark_last_approved_plan(memory: MemorySnapshot, run: ScenarioRun) -> None:
    if run.approval_status in FINAL_APPROVAL_STATUSES and run.result_plan_id:
        if run.result_plan_id not in memory.last_approved_plan_ids:
            memory.last_approved_plan_ids.append(run.result_plan_id)


def _refresh_run_from_state(state: SystemState, run: ScenarioRun) -> None:
    decision_log = _latest_decision(state)
    run.result_plan_id = state.latest_plan_id
    run.decision_id = decision_log.decision_id if decision_log else run.decision_id
    run.result_kpis = state.kpis.model_copy(deep=True)
    run.approval_status = (
        decision_log.approval_status.value if decision_log else ApprovalStatus.NOT_REQUIRED.value
    )


def apply_learning(state: SystemState, run: ScenarioRun) -> None:
    supplier_updates, route_updates = _update_numeric_learning(state, run)
    _refresh_run_from_state(state, run)
    if run.approval_status in FINAL_APPROVAL_STATUSES:
        run.reflection_status = "completed"
    elif run.approval_status == ApprovalStatus.PENDING.value:
        run.reflection_status = "pending_approval"
    else:
        run.reflection_status = "not_executed"

    run.outcome_summary = _build_outcome_summary(
        state,
        run,
        _latest_decision(state),
        supplier_updates,
        route_updates,
    )
    if run.reflection_status == "completed":
        _finalize_reflection_note(state, run)
        run.outcome_summary["reflection_status"] = run.reflection_status
        run.outcome_summary["reflection_note_id"] = run.reflection_note_id

    memory = state.memory or default_memory()
    _mark_last_approved_plan(memory, run)
    state.memory = MemorySnapshot.model_validate(memory.model_dump())
    _save_outcome_summary(state, run)


def finalize_latest_scenario_run(state: SystemState) -> ScenarioRun | None:
    run = _latest_run(state)
    if run is None:
        return None

    previous_status = run.reflection_status
    _refresh_run_from_state(state, run)
    if run.approval_status in FINAL_APPROVAL_STATUSES:
        run.reflection_status = "completed"
        _finalize_reflection_note(state, run)
    elif run.approval_status == ApprovalStatus.PENDING.value:
        run.reflection_status = "pending_approval"
    else:
        run.reflection_status = "not_executed"

    supplier_updates = run.outcome_summary.get("supplier_updates", {})
    route_updates = run.outcome_summary.get("route_updates", {})
    run.outcome_summary = _build_outcome_summary(
        state,
        run,
        _latest_decision(state),
        supplier_updates,
        route_updates,
    )
    memory = state.memory or default_memory()
    _mark_last_approved_plan(memory, run)
    state.memory = MemorySnapshot.model_validate(memory.model_dump())
    _save_outcome_summary(state, run)
    if previous_status != run.reflection_status:
        run.status = "completed"
    return run
