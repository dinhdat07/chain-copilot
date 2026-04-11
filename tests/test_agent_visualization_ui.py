from pathlib import Path

from core.memory import SQLiteStore
from core.state import load_initial_state
from orchestrator.service import approve_pending_plan
from simulation.runner import ScenarioRunner
from ui.components import (
    agent_node_payload,
    candidate_plan_dataframe,
    latest_reflection_snapshot,
    pipeline_graph_source,
    pipeline_node_status_map,
    reflection_timeline_dataframe,
)


def test_pipeline_graph_and_status_show_approval_branch() -> None:
    state = ScenarioRunner().run(load_initial_state(), "supplier_delay")

    graph = pipeline_graph_source(state)
    statuses = pipeline_node_status_map(state)

    assert "Risk Agent" in graph
    assert "Planner Agent" in graph
    assert "Approval Gate" in graph
    assert "decision_engine -> approval_gate" in graph
    assert statuses["approval_gate"]["tone"] == "approval"
    assert statuses["reflection_memory"]["tone"] == "approval"


def test_candidate_plan_dataframe_highlights_selected_strategy() -> None:
    state = ScenarioRunner().run(load_initial_state(), "supplier_delay")

    frame = candidate_plan_dataframe(state)

    assert len(frame) == 3
    assert frame["selected"].sum() == 1
    assert set(frame["strategy"]) == {"cost_first", "balanced", "resilience_first"}
    selected_row = frame.loc[frame["selected"]].iloc[0]
    assert selected_row["strategy"] == state.latest_plan.strategy_label


def test_reflection_snapshot_and_timeline_use_memory_notes(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "chaincopilot-agent-ui.db")
    runner = ScenarioRunner(store=store)
    state = runner.run(load_initial_state(), "route_blockage")
    state = approve_pending_plan(state, store, state.decision_logs[-1].decision_id, True)

    latest = latest_reflection_snapshot(state)
    timeline = reflection_timeline_dataframe(state)

    assert latest is not None
    assert latest["summary"]
    assert latest["pattern_tags"]
    assert len(timeline) == 1
    assert timeline.iloc[0]["scenario_id"] == "route_blockage"


def test_planner_payload_exposes_candidate_and_selection_context() -> None:
    state = ScenarioRunner().run(load_initial_state(), "supplier_delay")

    payload = agent_node_payload(state, "planner")

    assert payload["title"] == "Planner Agent"
    assert payload["summary"]
    assert payload["reasoning_source"]
    input_summary = payload["input_summary"]
    assert "Candidate plans" in set(input_summary["field"])
    assert "Selected strategy" in set(input_summary["field"])
