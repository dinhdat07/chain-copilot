from pathlib import Path

from core.memory import SQLiteStore
from core.state import load_initial_state
from llm.gemini_client import GeminiClientError
from orchestrator.service import request_safer_plan
from simulation.runner import ScenarioRunner


def _enable_llm(monkeypatch) -> None:
    monkeypatch.setenv("CHAINCOPILOT_LLM_ENABLED", "true")
    monkeypatch.setenv("CHAINCOPILOT_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("CHAINCOPILOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("CHAINCOPILOT_LLM_MODEL", "gemini-2.5-flash")


def _fake_response(*args, **kwargs) -> dict:
    return {
        "planner_narrative": "AI planner narrative based on the selected control tower plan.",
        "operator_explanation": "AI operator explanation grounded in KPI deltas and risk trade-offs.",
        "approval_summary": "High-risk plan requires approval because disruption severity and recovery trade-offs are elevated.",
    }


def test_llm_disabled_keeps_deterministic_fallback(monkeypatch) -> None:
    monkeypatch.delenv("CHAINCOPILOT_LLM_ENABLED", raising=False)
    monkeypatch.delenv("CHAINCOPILOT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    state = ScenarioRunner().graph.invoke(load_initial_state(), None)
    log = state.decision_logs[-1]

    assert state.latest_plan is not None
    assert state.latest_plan.llm_planner_narrative is None
    assert log.llm_operator_explanation is None
    assert log.llm_approval_summary is None
    assert log.llm_used is False
    assert log.rationale


def test_llm_enriches_normal_plan(monkeypatch) -> None:
    _enable_llm(monkeypatch)
    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _fake_response)

    state = ScenarioRunner().graph.invoke(load_initial_state(), None)
    log = state.decision_logs[-1]

    assert state.latest_plan is not None
    assert state.latest_plan.llm_planner_narrative == _fake_response()["planner_narrative"]
    assert log.llm_operator_explanation == _fake_response()["operator_explanation"]
    assert log.llm_used is True
    assert log.llm_provider == "gemini"
    assert log.llm_model == "gemini-2.5-flash"


def test_llm_generates_approval_summary(monkeypatch) -> None:
    _enable_llm(monkeypatch)
    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _fake_response)

    result = ScenarioRunner().run(load_initial_state(), "supplier_delay")
    log = result.decision_logs[-1]

    assert log.approval_required is True
    assert log.llm_approval_summary == _fake_response()["approval_summary"]


def test_llm_enriches_safer_plan_path(monkeypatch, tmp_path: Path) -> None:
    _enable_llm(monkeypatch)
    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _fake_response)
    store = SQLiteStore(tmp_path / "chaincopilot-llm.db")
    runner = ScenarioRunner(store=store)

    state = runner.run(load_initial_state(), "supplier_delay")
    decision_id = state.decision_logs[-1].decision_id
    updated = request_safer_plan(state, store, decision_id)

    assert updated.latest_plan is not None
    assert updated.latest_plan.llm_planner_narrative == _fake_response()["planner_narrative"]
    assert updated.decision_logs[-1].llm_operator_explanation == _fake_response()["operator_explanation"]


def test_llm_failure_falls_back_to_deterministic_reasoning(monkeypatch) -> None:
    _enable_llm(monkeypatch)

    def _raise_error(*args, **kwargs):
        raise GeminiClientError("gemini unavailable")

    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _raise_error)

    state = ScenarioRunner().graph.invoke(load_initial_state(), None)
    log = state.decision_logs[-1]

    assert state.latest_plan is not None
    assert state.latest_plan.llm_planner_narrative is None
    assert log.llm_used is False
    assert "gemini unavailable" in (log.llm_error or "")
    assert log.rationale
