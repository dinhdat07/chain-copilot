import json
import sqlite3
from pathlib import Path

from core.memory import SQLiteStore
from core.state import load_initial_state
from orchestrator.service import approve_pending_plan
from simulation.runner import ScenarioRunner


def test_decision_log_contains_grounded_explanation() -> None:
    state = load_initial_state()
    result = ScenarioRunner().run(state, "compound_disruption")
    decision = result.decision_logs[-1]

    assert set(decision.score_breakdown) == {
        "service_level",
        "total_cost",
        "disruption_risk",
        "recovery_speed",
    }
    assert "service level" in decision.rationale.lower()
    assert "total cost" in decision.rationale.lower()
    assert "disruption risk" in decision.rationale.lower()
    assert "recovery speed" in decision.rationale.lower()
    assert decision.winning_factors
    assert decision.approval_reason
    assert decision.approval_required is True
    assert decision.rejected_actions
    assert all(item["reason"] != "not selected in final plan" for item in decision.rejected_actions)


def test_scenario_run_persists_learned_memory_to_state_snapshot(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "chaincopilot.db")
    state = load_initial_state()
    initial_reliability = next(
        record.reliability
        for record in state.suppliers.values()
        if record.supplier_id == "SUP_A"
    )

    result = ScenarioRunner(store=store).run(state, "supplier_delay")

    assert result.memory is not None
    assert result.memory.supplier_reliability["SUP_A"] < initial_reliability
    assert result.memory.scenario_outcomes["supplier_delay"]["runs"] == 1
    assert result.scenario_history[-1].reflection_status == "pending_approval"

    with sqlite3.connect(store.path) as conn:
        row = conn.execute("SELECT payload FROM state_snapshots WHERE run_id = ?", (result.run_id,)).fetchone()
    payload = json.loads(row[0])
    assert payload["memory"]["supplier_reliability"]["SUP_A"] == result.memory.supplier_reliability["SUP_A"]
    assert payload["memory"]["scenario_outcomes"]["supplier_delay"]["runs"] == 1


def test_repeated_scenario_runs_accumulate_memory_history(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "chaincopilot.db")
    runner = ScenarioRunner(store=store)
    state = load_initial_state()
    initial_prior = state.routes["R1"].risk_score

    state = runner.run(state, "route_blockage")
    if state.pending_plan and state.decision_logs:
        state = approve_pending_plan(state, store, state.decision_logs[-1].decision_id, True)
    state = runner.run(state, "route_blockage")
    if state.pending_plan and state.decision_logs:
        state = approve_pending_plan(state, store, state.decision_logs[-1].decision_id, True)

    assert state.memory is not None
    history = state.memory.scenario_outcomes["route_blockage"]["history"]
    assert state.memory.scenario_outcomes["route_blockage"]["runs"] == 2
    assert len(history) == 2
    assert state.memory.route_disruption_priors["R1"] > initial_prior
    assert len(state.scenario_history) == 2
    assert len(state.memory.reflection_notes) == 2
    assert state.scenario_history[-1].reflection_status == "completed"

    with sqlite3.connect(store.path) as conn:
        row_count = conn.execute("SELECT COUNT(*) FROM scenario_runs").fetchone()[0]
    assert row_count == 2
