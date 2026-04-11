from llm.gemini_client import GeminiClientError
from core.enums import EventType, Mode
from core.models import Event
from core.state import load_initial_state, utc_now
from orchestrator.graph import build_graph


def _enable_llm(monkeypatch) -> None:
    monkeypatch.setenv("CHAINCOPILOT_LLM_ENABLED", "true")
    monkeypatch.setenv("CHAINCOPILOT_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("CHAINCOPILOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("CHAINCOPILOT_LLM_MODEL", "gemini-2.5-flash")


def _event(event_type: EventType, severity: float, payload: dict, entity_ids: list[str]) -> Event:
    return Event(
        event_id=f"evt_{event_type.value}_{severity}",
        type=event_type,
        source="test",
        severity=severity,
        entity_ids=entity_ids,
        occurred_at=utc_now(),
        detected_at=utc_now(),
        payload=payload,
        dedupe_key=f"{event_type.value}:{entity_ids}:{payload}",
    )


def test_normal_mode_creates_three_candidate_evaluations(monkeypatch) -> None:
    _enable_llm(monkeypatch)

    def _fake_generate_json(self, *, prompt, schema, temperature=0.2):
        if "candidate_plans" in schema.get("properties", {}):
            return {
                "candidate_plans": [
                    {
                        "strategy_label": "cost_first",
                        "action_ids": ["act_reorder_SKU_2"],
                        "rationale": "Minimize incremental spend.",
                    },
                    {
                        "strategy_label": "balanced",
                        "action_ids": ["act_reorder_SKU_1", "act_reorder_SKU_2"],
                        "rationale": "Protect service while keeping cost moderate.",
                    },
                    {
                        "strategy_label": "resilience_first",
                        "action_ids": ["act_reorder_SKU_1", "act_reorder_SKU_2", "act_reorder_SKU_3"],
                        "rationale": "Prioritize network resilience.",
                    },
                ]
            }
        if "summary" in schema.get("properties", {}):
            return {
                "summary": "Balanced plan avoids overreacting in a calm operating state.",
                "findings": ["Cost-first leaves more downside if demand shifts unexpectedly."],
            }
        return {
            "planner_narrative": "AI narrative",
            "operator_explanation": "AI operator explanation",
            "approval_summary": "",
        }

    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _fake_generate_json)

    result = build_graph().invoke(load_initial_state(), None)
    log = result.decision_logs[-1]

    assert result.latest_plan is not None
    assert len(log.candidate_evaluations) == 3
    assert {item.strategy_label for item in log.candidate_evaluations} == {
        "cost_first",
        "balanced",
        "resilience_first",
    }
    assert result.latest_plan.strategy_label in {"cost_first", "balanced", "resilience_first"}
    assert log.selection_reason
    assert log.critic_used is True


def test_crisis_mode_can_select_resilience_first(monkeypatch) -> None:
    _enable_llm(monkeypatch)

    def _fake_generate_json(self, *, prompt, schema, temperature=0.2):
        if "candidate_plans" in schema.get("properties", {}):
            return {
                "candidate_plans": [
                    {
                        "strategy_label": "cost_first",
                        "action_ids": ["act_reorder_SKU_3"],
                        "rationale": "Choose the smallest replenishment move.",
                    },
                    {
                        "strategy_label": "balanced",
                        "action_ids": ["act_reorder_SKU_2"],
                        "rationale": "Restore the most directly affected SKU.",
                    },
                    {
                        "strategy_label": "resilience_first",
                        "action_ids": ["act_demand_rebalance_SKU_2", "act_reorder_SKU_2"],
                        "rationale": "Combine repositioning and replenishment for the disrupted SKU.",
                    },
                ]
            }
        if "summary" in schema.get("properties", {}):
            return {"summary": "Resilience-first best matches the disruption profile.", "findings": []}
        return {
            "planner_narrative": "AI narrative",
            "operator_explanation": "AI operator explanation",
            "approval_summary": "Approval summary",
        }

    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _fake_generate_json)

    event = _event(
        EventType.DEMAND_SPIKE,
        0.7,
        {"sku": "SKU_2", "multiplier": 2.2},
        ["SKU_2"],
    )
    result = build_graph().invoke(load_initial_state(), event)

    assert result.mode in {Mode.CRISIS, Mode.APPROVAL}
    assert result.latest_plan is not None
    assert result.latest_plan.strategy_label == "resilience_first"


def test_invalid_planner_output_falls_back_to_deterministic_candidates(monkeypatch) -> None:
    _enable_llm(monkeypatch)

    def _fake_generate_json(self, *, prompt, schema, temperature=0.2):
        if "candidate_plans" in schema.get("properties", {}):
            return {
                "candidate_plans": [
                    {
                        "strategy_label": "cost_first",
                        "action_ids": ["missing_action"],
                        "rationale": "Invalid action should trigger fallback.",
                    }
                ]
            }
        if "summary" in schema.get("properties", {}):
            return {"summary": "", "findings": []}
        return {
            "planner_narrative": "AI narrative",
            "operator_explanation": "AI operator explanation",
            "approval_summary": "",
        }

    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _fake_generate_json)

    result = build_graph().invoke(load_initial_state(), None)
    log = result.decision_logs[-1]

    assert result.latest_plan is not None
    assert result.latest_plan.generated_by == "hybrid_fallback"
    assert len(log.candidate_evaluations) == 3
    assert "invalid candidate plans" in (log.planner_error or "")
    assert result.agent_outputs["planner"].llm_error is not None


def test_critic_failure_does_not_break_planning(monkeypatch) -> None:
    _enable_llm(monkeypatch)

    def _fake_generate_json(self, *, prompt, schema, temperature=0.2):
        if "candidate_plans" in schema.get("properties", {}):
            return {
                "candidate_plans": [
                    {
                        "strategy_label": "cost_first",
                        "action_ids": ["act_reorder_SKU_2"],
                        "rationale": "Lowest-cost move.",
                    },
                    {
                        "strategy_label": "balanced",
                        "action_ids": ["act_reorder_SKU_1", "act_reorder_SKU_2"],
                        "rationale": "Balanced coverage.",
                    },
                    {
                        "strategy_label": "resilience_first",
                        "action_ids": ["act_reorder_SKU_1", "act_reorder_SKU_2", "act_reorder_SKU_3"],
                        "rationale": "Fastest recovery posture.",
                    },
                ]
            }
        if "summary" in schema.get("properties", {}):
            raise GeminiClientError("critic unavailable")
        return {
            "planner_narrative": "AI narrative",
            "operator_explanation": "AI operator explanation",
            "approval_summary": "",
        }

    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _fake_generate_json)

    result = build_graph().invoke(load_initial_state(), None)
    log = result.decision_logs[-1]

    assert result.latest_plan is not None
    assert log.critic_used is False
    assert "critic unavailable" in (log.critic_error or "")
