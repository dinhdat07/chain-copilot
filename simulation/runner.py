from __future__ import annotations

import time
from uuid import uuid4

from core.memory import SQLiteStore
from core.models import ScenarioRun, SystemState
from core.state import clone_state
from orchestrator.graph import build_graph
from simulation.learning import apply_learning
from simulation.scenarios import get_scenario_events


class ScenarioRunner:
    def __init__(self, store: SQLiteStore | None = None) -> None:
        self.graph = build_graph()
        self.store = store or SQLiteStore()

    def run(self, initial_state: SystemState, scenario_name: str, seed: int = 7) -> SystemState:
        state = clone_state(initial_state)
        started = time.perf_counter()
        events = get_scenario_events(scenario_name)
        for event in events:
            state = self.graph.invoke(state, event)
        run = ScenarioRun(
            run_id=f"run_{uuid4().hex[:8]}",
            scenario_id=scenario_name,
            seed=seed,
            events=events,
            result_plan_id=state.latest_plan_id,
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
