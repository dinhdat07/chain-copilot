from __future__ import annotations

import time
from uuid import uuid4

from core.memory import SQLiteStore
from core.models import ScenarioRun, SystemState
from core.runtime_records import EventClass, EventEnvelope, RunType
from core.runtime_tracking import (
    build_execution_record,
    build_run_record,
    clone_trace_for_run,
    new_correlation_id,
    new_event_envelope_id,
    new_run_id,
)
from core.state import clone_state
from orchestrator.graph import build_graph
from orchestrator.service import ensure_no_pending_plan
from simulation.learning import apply_learning
from simulation.scenarios import get_scenario_events


class ScenarioRunner:
    def __init__(self, store: SQLiteStore | None = None) -> None:
        self.graph = build_graph()
        self.store = store or SQLiteStore()

    def run(self, initial_state: SystemState, scenario_name: str, seed: int = 7) -> SystemState:
        ensure_no_pending_plan(initial_state)
        state = clone_state(initial_state)
        started = time.perf_counter()
        events = get_scenario_events(scenario_name)
        scenario_correlation_id = new_correlation_id("scenario")
        for event in events:
            started_at = event.detected_at
            parent_run_id = state.run_id
            run_id = new_run_id()
            envelope = EventEnvelope(
                event_id=new_event_envelope_id(),
                event_class=EventClass.DOMAIN,
                event_type=event.type.value,
                source=f"scenario:{scenario_name}",
                occurred_at=event.occurred_at,
                ingested_at=event.detected_at,
                correlation_id=scenario_correlation_id,
                causation_id=None,
                idempotency_key=event.dedupe_key,
                severity=event.severity,
                entity_ids=event.entity_ids,
                payload=event.payload,
            )
            self.store.save_event_envelope(envelope)
            state = self.graph.invoke(state, event, run_id=run_id)
            decision = state.decision_logs[-1] if state.decision_logs else None
            execution = build_execution_record(run_id=run_id, state=state, decision=decision)
            if execution is not None:
                self.store.save_execution_record(execution)
            run_record = build_run_record(
                run_id=run_id,
                run_type=RunType.SCENARIO_STEP,
                state=state,
                started_at=started_at,
                parent_run_id=parent_run_id,
                envelope=envelope,
                execution_id=execution.execution_id if execution is not None else None,
            )
            self.store.save_run_record(run_record)
            trace = clone_trace_for_run(state.latest_trace, run_id)
            if trace is not None:
                self.store.save_trace(run_id, trace)
            self.store.save_state(state)
            if decision is not None:
                self.store.save_decision_log(decision)
        run = ScenarioRun(
            run_id=f"run_{uuid4().hex[:8]}",
            scenario_id=scenario_name,
            seed=seed,
            events=events,
            result_plan_id=state.latest_plan_id,
            decision_id=state.decision_logs[-1].decision_id if state.decision_logs else None,
            result_kpis=state.kpis,
            duration_ms=round((time.perf_counter() - started) * 1000.0, 2),
            status="completed",
        )
        state.scenario_history.append(run)
        apply_learning(state, run)
        self.store.save_scenario_run(run)
        self.store.save_state(state)
        if state.decision_logs:
            self.store.save_decision_log(state.decision_logs[-1])
        return state
