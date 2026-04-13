from core.enums import ActionType, EventType
from core.models import Action, Event
from core.state import load_initial_state, utc_now
from llm.service import generate_candidate_plan_drafts
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


def test_generate_candidate_plan_drafts_normalizes_strategy_aliases(monkeypatch) -> None:
    _enable_llm(monkeypatch)

    def _fake_generate_json(self, *, prompt, schema, temperature=0.2):
        return {
            "candidate_plans": [
                {"strategy_label": "Plan A", "action_ids": ["act_reorder_SKU_1"], "rationale": "lowest cost option"},
                {"strategy_label": "Balanced plan", "action_ids": ["act_reorder_SKU_2"], "rationale": "balanced coverage"},
                {"strategy_label": "Recovery-first", "action_ids": ["act_reorder_SKU_3"], "rationale": "recovery resilience focus"},
            ]
        }

    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _fake_generate_json)
    state = load_initial_state()
    candidate_actions = [
        Action(action_id="act_reorder_SKU_1", action_type=ActionType.REORDER, target_id="SKU_1"),
        Action(action_id="act_reorder_SKU_2", action_type=ActionType.REORDER, target_id="SKU_2"),
        Action(action_id="act_reorder_SKU_3", action_type=ActionType.REORDER, target_id="SKU_3"),
    ]

    drafts, error = generate_candidate_plan_drafts(
        state=state,
        event=None,
        candidate_actions=candidate_actions,
    )

    assert error is None
    assert [draft.strategy_label for draft in drafts] == ["cost_first", "balanced", "resilience_first"]


def test_generate_candidate_plan_drafts_normalizes_action_aliases(monkeypatch) -> None:
    _enable_llm(monkeypatch)

    def _fake_generate_json(self, *, prompt, schema, temperature=0.2):
        return {
            "candidate_plans": [
                {
                    "strategy_label": "cost_first",
                    "actions": [{"id": "SUP_B"}],
                    "rationale": "switch to alternate supplier cheaply",
                },
                {
                    "strategy_label": "balanced",
                    "recommended_action_ids": ["R4"],
                    "rationale": "protect lane reliability",
                },
                {
                    "strategy_label": "resilience_first",
                    "selected_actions": ["rebalance SKU_2"],
                    "rationale": "restore service fast",
                },
            ]
        }

    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _fake_generate_json)
    state = load_initial_state()
    candidate_actions = [
        Action(
            action_id="act_supplier_SKU_1_SUP_B",
            action_type=ActionType.SWITCH_SUPPLIER,
            target_id="SKU_1",
            parameters={"supplier_id": "SUP_B"},
        ),
        Action(
            action_id="act_reroute_SKU_1_R4",
            action_type=ActionType.REROUTE,
            target_id="SKU_1",
            parameters={"route_id": "R4"},
        ),
        Action(
            action_id="act_demand_rebalance_SKU_2",
            action_type=ActionType.REBALANCE,
            target_id="SKU_2",
            reason="rebalance SKU_2",
        ),
    ]

    drafts, error = generate_candidate_plan_drafts(
        state=state,
        event=None,
        candidate_actions=candidate_actions,
    )

    assert error is None
    assert drafts[0].action_ids == ["act_supplier_SKU_1_SUP_B"]
    assert drafts[1].action_ids == ["act_reroute_SKU_1_R4"]
    assert drafts[2].action_ids == ["act_demand_rebalance_SKU_2"]


def test_partial_planner_output_is_repaired_not_fully_fallback(monkeypatch) -> None:
    _enable_llm(monkeypatch)

    def _fake_generate_json(self, *, prompt, schema, temperature=0.2):
        if "candidate_plans" in schema.get("properties", {}):
            return {
                "candidate_plans": [
                    {
                        "strategy_label": "Plan A",
                        "action_ids": ["act_supplier_SKU_001_SUP_B"],
                        "rationale": "cheap supplier substitution",
                    },
                    {
                        "strategy_label": "Plan B",
                        "recommended_action_ids": ["R2"],
                        "rationale": "balanced route protection",
                    },
                ]
            }
        if "summary" in schema.get("properties", {}):
            return {"summary": "critic ok", "findings": []}
        return {
            "planner_narrative": "AI narrative",
            "operator_explanation": "AI operator explanation",
            "approval_summary": "AI approval summary",
        }

    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _fake_generate_json)
    state = load_initial_state()
    event = _event(
        EventType.SUPPLIER_DELAY,
        0.8,
        {"supplier_id": "SUP_A", "sku": "SKU_001", "delay_hours": 48},
        ["SUP_A", "SKU_001"],
    )

    result = build_graph().invoke(state, event)

    assert result.latest_plan is not None
    assert result.latest_plan.generated_by == "llm_planner_repaired"
    assert len(result.decision_logs[-1].candidate_evaluations) == 3
    assert "planner returned incomplete or invalid candidate plans" in (
        result.decision_logs[-1].planner_error or ""
    )
