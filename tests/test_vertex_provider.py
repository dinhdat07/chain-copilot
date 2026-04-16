from __future__ import annotations

import json

from core.enums import EventType
from core.models import Event
from core.state import load_initial_state, utc_now
from llm.config import load_settings
from llm.vertex_client import VertexGeminiClient
from llm.vertex_client import VertexClientError
from orchestrator.graph import build_graph


def _enable_vertex(monkeypatch) -> None:
    monkeypatch.setenv("CHAINCOPILOT_LLM_ENABLED", "true")
    monkeypatch.setenv("CHAINCOPILOT_LLM_PROVIDER", "vertex")
    monkeypatch.setenv("VERTEX_AI_API_KEY", "vertex-test-key")
    monkeypatch.setenv("VERTEX_AI_PROJECT_ID", "vertex-test-project")
    monkeypatch.setenv("VERTEX_AI_REGION", "global")
    monkeypatch.setenv("CHAINCOPILOT_LLM_MODEL", "gemini-2.5-flash")


def _event() -> Event:
    return Event(
        event_id="evt_supplier_delay_vertex",
        type=EventType.SUPPLIER_DELAY,
        source="test",
        severity=0.82,
        entity_ids=["SUP_BN", "SKU_001"],
        occurred_at=utc_now(),
        detected_at=utc_now(),
        payload={"supplier_id": "SUP_BN", "sku": "SKU_001", "delay_hours": 48},
        dedupe_key="supplier_delay:SUP_A:SKU_001:48",
    )


def test_load_settings_prefers_vertex_env(monkeypatch) -> None:
    _enable_vertex(monkeypatch)

    settings = load_settings()

    assert settings.provider == "vertex"
    assert settings.api_key == "vertex-test-key"
    assert settings.vertex_project_id == "vertex-test-project"
    assert settings.vertex_region == "global"


def test_vertex_provider_routes_planner_without_fallback(monkeypatch) -> None:
    _enable_vertex(monkeypatch)

    def _fake_generate_json(self, *, prompt, schema, temperature=0.2):
        if "candidate_plans" in schema.get("properties", {}):
            return {
                "candidate_plans": [
                    {
                        "strategy_label": "cost_first",
                        "action_ids": ["act_supplier_SKU_001_SUP_HP"],
                        "rationale": "Use the lower-cost alternate supplier.",
                    },
                    {
                        "strategy_label": "balanced",
                        "action_ids": ["act_supplier_SKU_004_SUP_HP"],
                        "rationale": "Balance supplier and route risk.",
                    },
                    {
                        "strategy_label": "resilience_first",
                        "action_ids": ["act_supplier_SKU_007_SUP_HP"],
                        "rationale": "Protect recovery speed under disruption.",
                    },
                ]
            }
        if "summary" in schema.get("properties", {}):
            return {
                "summary": "Vertex critic accepted the plan.",
                "findings": [],
            }
        if "planner_narrative" in schema.get("properties", {}):
            return {
                "planner_narrative": "Vertex planner narrative.",
                "operator_explanation": "Vertex operator explanation.",
                "approval_summary": "Vertex approval summary.",
            }
        return {
            "domain_summary": "Vertex specialist reasoning.",
            "downstream_impacts": ["Monitor downstream service impact."],
            "recommended_action_ids": [],
            "tradeoffs": ["Lower cost can increase supplier transition risk."],
            "notes_for_planner": "Prefer resilient substitutes for disrupted supply.",
        }

    monkeypatch.setattr(
        "llm.service.VertexGeminiClient.generate_json", _fake_generate_json
    )

    result = build_graph().invoke(load_initial_state(), _event())
    log = result.decision_logs[-1]

    assert result.latest_plan is not None
    assert result.latest_plan.generated_by == "llm_planner"
    assert log.planner_error is None
    assert result.agent_outputs["planner"].llm_used is True
    assert log.llm_provider == "vertex"
    assert log.llm_model == "gemini-2.5-flash"


def test_vertex_quota_error_keeps_existing_fallback(monkeypatch) -> None:
    _enable_vertex(monkeypatch)

    def _raise_quota(self, *, prompt, schema, temperature=0.2):
        raise VertexClientError("vertex quota error 429: quota exhausted")

    monkeypatch.setattr("llm.service.VertexGeminiClient.generate_json", _raise_quota)

    result = build_graph().invoke(load_initial_state(), _event())
    log = result.decision_logs[-1]

    assert result.latest_plan is not None
    assert result.latest_plan.generated_by == "hybrid_fallback"
    assert "vertex quota error 429" in (log.planner_error or "")
    assert result.agent_outputs["planner"].llm_error is not None


def test_vertex_client_sends_user_role(monkeypatch) -> None:
    _enable_vertex(monkeypatch)
    captured: dict[str, object] = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": json.dumps({"ok": True}),
                                    }
                                ]
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    def _fake_urlopen(http_request, timeout):
        captured["body"] = json.loads(http_request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("llm.vertex_client.request.urlopen", _fake_urlopen)

    settings = load_settings()
    result = VertexGeminiClient(settings).generate_json(
        prompt="test prompt",
        schema={"type": "object"},
    )

    assert result == {"ok": True}
    assert captured["body"]["contents"][0]["role"] == "user"
