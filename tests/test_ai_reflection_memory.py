from pathlib import Path

from core.enums import ApprovalStatus, EventType
from core.memory import SQLiteStore
from core.models import ReflectionNote, ScenarioRun
from core.state import load_initial_state
from orchestrator.service import approve_pending_plan
from simulation.learning import apply_learning
from simulation.runner import ScenarioRunner


def _reflection_note(run: ScenarioRun, approval_status: str) -> ReflectionNote:
    return ReflectionNote(
        note_id=f"note_{run.run_id}",
        run_id=run.run_id,
        scenario_id=run.scenario_id,
        plan_id=run.result_plan_id,
        event_types=[event.type.value for event in run.events],
        mode="crisis" if approval_status != ApprovalStatus.NOT_REQUIRED.value else "normal",
        approval_status=approval_status,
        summary=f"Reflection for {run.scenario_id}",
        lessons=["keep alternates warm", "review approvals faster"],
        pattern_tags=[run.scenario_id, "approval"],
        follow_up_checks=["review priors", "replay scenario"],
        llm_used=True,
        llm_error=None,
    )


def test_auto_applied_run_persists_reflection_note(monkeypatch) -> None:
    from simulation.scenarios import build_event
    from orchestrator.graph import build_graph

    def _fake_reflection(*, state, run, decision_log):
        return _reflection_note(run, run.approval_status or ApprovalStatus.NOT_REQUIRED.value), None

    monkeypatch.setattr("simulation.learning.generate_reflection_note", _fake_reflection)

    state = load_initial_state()
    event = build_event(
        event_id="evt_low_demand",
        event_type=EventType.DEMAND_SPIKE,
        severity=0.35,
        payload={"sku": "SKU_2", "multiplier": 1.2},
        entity_ids=["SKU_2"],
    )
    state = build_graph().invoke(state, event)
    run = ScenarioRun(
        run_id="run_auto_reflect",
        scenario_id="manual_low_demand",
        seed=7,
        events=[event],
        result_plan_id=state.latest_plan_id,
        decision_id=state.decision_logs[-1].decision_id,
        result_kpis=state.kpis,
        status="completed",
    )
    state.scenario_history.append(run)
    apply_learning(state, run)

    assert state.decision_logs[-1].approval_status == ApprovalStatus.AUTO_APPLIED
    assert state.memory is not None
    assert len(state.memory.reflection_notes) == 1
    assert state.memory.reflection_notes[0].llm_used is True
    assert run.reflection_status == "completed"
    assert run.reflection_note_id == state.memory.reflection_notes[0].note_id


def test_pending_approval_run_defers_reflection(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "chaincopilot.db")
    state = ScenarioRunner(store=store).run(load_initial_state(), "supplier_delay")

    assert state.pending_plan is not None
    assert state.memory is not None
    assert state.memory.reflection_notes == []
    assert state.scenario_history[-1].reflection_status == "pending_approval"
    assert state.scenario_history[-1].reflection_note_id is None


def test_approving_pending_run_finalizes_reflection(monkeypatch, tmp_path: Path) -> None:
    def _fake_reflection(*, state, run, decision_log):
        return _reflection_note(run, run.approval_status or ApprovalStatus.APPROVED.value), None

    monkeypatch.setattr("simulation.learning.generate_reflection_note", _fake_reflection)
    store = SQLiteStore(tmp_path / "chaincopilot.db")
    runner = ScenarioRunner(store=store)
    state = runner.run(load_initial_state(), "supplier_delay")
    decision_id = state.decision_logs[-1].decision_id

    updated = approve_pending_plan(state, store, decision_id, True)

    assert updated.memory is not None
    assert len(updated.memory.reflection_notes) == 1
    assert updated.scenario_history[-1].reflection_status == "completed"
    assert updated.scenario_history[-1].reflection_note_id == updated.memory.reflection_notes[0].note_id
    assert updated.scenario_history[-1].approval_status == ApprovalStatus.APPROVED.value


def test_repeated_runs_accumulate_reflection_tags(monkeypatch, tmp_path: Path) -> None:
    def _fake_reflection(*, state, run, decision_log):
        note = _reflection_note(run, run.approval_status or ApprovalStatus.APPROVED.value)
        note.pattern_tags = ["route_blockage", "resilience"]
        return note, None

    monkeypatch.setattr("simulation.learning.generate_reflection_note", _fake_reflection)
    store = SQLiteStore(tmp_path / "chaincopilot.db")
    runner = ScenarioRunner(store=store)
    state = load_initial_state()

    state = runner.run(state, "route_blockage")
    state = approve_pending_plan(state, store, state.decision_logs[-1].decision_id, True)
    state = runner.run(state, "route_blockage")
    state = approve_pending_plan(state, store, state.decision_logs[-1].decision_id, True)

    assert state.memory is not None
    assert len(state.memory.reflection_notes) == 2
    assert state.memory.pattern_tag_counts["route_blockage"] == 2
    assert state.memory.pattern_tag_counts["resilience"] == 2


def test_reflection_falls_back_when_llm_unavailable(monkeypatch, tmp_path: Path) -> None:
    def _failed_reflection(*, state, run, decision_log):
        return None, "reflection llm unavailable"

    monkeypatch.setattr("simulation.learning.generate_reflection_note", _failed_reflection)
    store = SQLiteStore(tmp_path / "chaincopilot.db")
    runner = ScenarioRunner(store=store)
    state = runner.run(load_initial_state(), "supplier_delay")

    updated = approve_pending_plan(state, store, state.decision_logs[-1].decision_id, True)

    assert updated.memory is not None
    note = updated.memory.reflection_notes[0]
    assert note.llm_used is False
    assert note.llm_error == "reflection llm unavailable"
    assert note.summary
