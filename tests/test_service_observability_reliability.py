from pathlib import Path

from fastapi.testclient import TestClient

import api
from core.enums import ActionType
from core.memory import SQLiteStore
from core.models import Action
from core.state import load_initial_state
from llm.gemini_client import GeminiClientError
from llm.service import generate_candidate_plan_drafts
from orchestrator.graph import build_graph
from simulation.runner import ScenarioRunner


def _client(tmp_path: Path) -> TestClient:
    store = SQLiteStore(tmp_path / "chaincopilot-service-runtime.db")
    api.replace_runtime(
        store=store,
        state=load_initial_state(),
        graph=build_graph(),
        runner=ScenarioRunner(store=store),
    )
    return TestClient(api.app)


def _enable_llm(monkeypatch) -> None:
    monkeypatch.setenv("CHAINCOPILOT_LLM_ENABLED", "true")
    monkeypatch.setenv("CHAINCOPILOT_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("CHAINCOPILOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("CHAINCOPILOT_LLM_MODEL", "gemini-2.5-flash")


def test_service_runtime_endpoint_exposes_flags_and_metrics(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHAINCOPILOT_LLM_ENABLED", "false")
    monkeypatch.setenv("CHAINCOPILOT_PLANNER_MODE", "deterministic")
    monkeypatch.setenv("CHAINCOPILOT_DISPATCH_MODE", "simulation")
    monkeypatch.setenv("CHAINCOPILOT_LLM_TIMEOUT_S", "6")
    monkeypatch.setenv("CHAINCOPILOT_LLM_RETRY_ATTEMPTS", "2")
    client = _client(tmp_path)

    command_response = client.post(
        "/api/v1/events/ingest",
        json={
            "event_class": "command",
            "event_type": "plan_requested",
            "source": "test",
            "payload": {"requested_by": "operator"},
        },
    )
    assert command_response.status_code == 200

    disruption_response = client.post(
        "/api/v1/events/ingest",
        json={
            "event_class": "domain",
            "event_type": "supplier_delay",
            "source": "test",
            "severity": 0.82,
            "entity_ids": ["SUP_A", "SKU_1"],
            "payload": {"supplier_id": "SUP_A", "sku": "SKU_1", "delay_hours": 48},
        },
    )
    assert disruption_response.status_code == 200

    response = client.get("/api/v1/service/runtime")

    assert response.status_code == 200
    payload = response.json()["item"]
    assert payload["flags"]["llm_enabled"] is False
    assert payload["flags"]["planner_mode"] == "deterministic"
    assert payload["flags"]["dispatch_mode"] == "simulation"
    assert payload["flags"]["llm_timeout_s"] == 6.0
    assert payload["flags"]["llm_retry_attempts"] == 2
    assert payload["metrics"]["total_runs"] >= 2
    assert payload["metrics"]["total_events"] >= 2
    assert payload["metrics"]["total_executions"] >= 2
    assert payload["metrics"]["avg_run_duration_ms"] >= 0.0
    assert payload["metrics"]["avg_agent_step_duration_ms"] >= 0.0
    assert payload["metrics"]["llm_fallback_rate"] >= 0.0
    assert payload["metrics"]["approval_rate"] > 0.0


def test_standard_error_envelope_for_not_found_and_validation(tmp_path: Path) -> None:
    client = _client(tmp_path)

    missing_response = client.get("/api/v1/runs/run_missing")
    assert missing_response.status_code == 404
    missing_payload = missing_response.json()
    assert missing_payload["code"] == "run_not_found"
    assert missing_payload["message"] == "run not found"
    assert missing_payload["details"]["id"] == "run_missing"

    validation_response = client.post(
        "/api/v1/approvals/dec_missing",
        json={"action": "invalid"},
    )
    assert validation_response.status_code == 422
    validation_payload = validation_response.json()
    assert validation_payload["code"] == "validation_error"
    assert validation_payload["message"] == "request validation failed"
    assert "errors" in validation_payload["details"]


def test_planner_mode_deterministic_skips_candidate_llm(monkeypatch) -> None:
    _enable_llm(monkeypatch)
    monkeypatch.setenv("CHAINCOPILOT_PLANNER_MODE", "deterministic")

    def _boom(self, *, prompt, schema, temperature=0.2):
        raise AssertionError("planner LLM should not be called in deterministic mode")

    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _boom)
    state = load_initial_state()
    candidate_actions = [
        Action(action_id="act_reorder_SKU_1", action_type=ActionType.REORDER, target_id="SKU_1")
    ]

    drafts, error = generate_candidate_plan_drafts(
        state=state,
        event=None,
        candidate_actions=candidate_actions,
    )

    assert drafts == []
    assert error == "planner_mode=deterministic"


def test_candidate_planner_retries_once_before_succeeding(monkeypatch) -> None:
    _enable_llm(monkeypatch)
    monkeypatch.setenv("CHAINCOPILOT_PLANNER_MODE", "hybrid")
    monkeypatch.setenv("CHAINCOPILOT_LLM_RETRY_ATTEMPTS", "2")
    calls = {"count": 0}

    def _flaky(self, *, prompt, schema, temperature=0.2):
        calls["count"] += 1
        if calls["count"] == 1:
            raise GeminiClientError("temporary timeout")
        return {
            "candidate_plans": [
                {"strategy_label": "cost_first", "action_ids": ["act_reorder_SKU_1"], "rationale": "retry ok"},
                {"strategy_label": "balanced", "action_ids": ["act_reorder_SKU_1"], "rationale": "retry ok"},
                {"strategy_label": "resilience_first", "action_ids": ["act_reorder_SKU_1"], "rationale": "retry ok"},
            ]
        }

    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _flaky)
    state = load_initial_state()
    candidate_actions = [
        Action(action_id="act_reorder_SKU_1", action_type=ActionType.REORDER, target_id="SKU_1")
    ]

    drafts, error = generate_candidate_plan_drafts(
        state=state,
        event=None,
        candidate_actions=candidate_actions,
    )

    assert calls["count"] == 2
    assert error is None
    assert [draft.strategy_label for draft in drafts] == ["cost_first", "balanced", "resilience_first"]
