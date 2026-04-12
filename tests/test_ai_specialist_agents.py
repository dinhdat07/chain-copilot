from agents.logistics import LogisticsAgent
from agents.supplier import SupplierAgent
from core.enums import Mode
from core.state import load_initial_state
from simulation.scenarios import get_scenario_events


def _enable_llm(monkeypatch) -> None:
    monkeypatch.setenv("CHAINCOPILOT_LLM_ENABLED", "true")
    monkeypatch.setenv("CHAINCOPILOT_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("CHAINCOPILOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("CHAINCOPILOT_LLM_MODEL", "gemini-2.5-flash")


def test_logistics_agent_uses_llm_ranked_actions(monkeypatch) -> None:
    _enable_llm(monkeypatch)

    def _fake_generate_json(self, *, prompt, schema, temperature=0.2):
        return {
            "domain_summary": "Flooding on the primary corridor makes reroute resilience more important than local transport cost.",
            "downstream_impacts": [
                "Haiphong deliveries may slip first.",
                "Lower-risk alternate lanes reduce follow-on disruption exposure.",
            ],
            "recommended_action_ids": [
                "act_reroute_SKU_3_R4",
                "act_reroute_SKU_1_R4",
            ],
            "tradeoffs": [
                "R4 is more expensive but materially safer.",
            ],
            "notes_for_planner": "Bias toward the safer route set if crisis conditions persist.",
        }

    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _fake_generate_json)

    state = load_initial_state()
    event = get_scenario_events("route_blockage")[0]
    proposal = LogisticsAgent().run(state, event)

    assert proposal.llm_used is True
    assert proposal.domain_summary
    assert proposal.recommended_action_ids == [
        "act_reroute_SKU_3_R4",
        "act_reroute_SKU_1_R4",
    ]
    assert proposal.proposals[0].action_id == "act_reroute_SKU_3_R4"
    assert proposal.proposals[0].priority > proposal.proposals[1].priority


def test_invalid_specialist_action_ids_fall_back_safely(monkeypatch) -> None:
    _enable_llm(monkeypatch)

    def _fake_generate_json(self, *, prompt, schema, temperature=0.2):
        return {
            "domain_summary": "Supplier substitution is urgent.",
            "downstream_impacts": ["Primary lead time degradation threatens replenishment."],
            "recommended_action_ids": ["missing_action_id"],
            "tradeoffs": ["Backup suppliers cost more."],
            "notes_for_planner": "Prefer fast supplier substitution.",
        }

    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _fake_generate_json)

    state = load_initial_state()
    event = get_scenario_events("supplier_delay")[0]
    proposal = SupplierAgent().run(state, event)

    assert proposal.llm_used is False
    assert proposal.llm_error == "llm returned no valid action ids"
    assert proposal.recommended_action_ids == []
    assert proposal.proposals[0].action_id == "act_supplier_SKU_1_SUP_B"


def test_disabled_specialist_llm_keeps_deterministic_supplier_behavior(monkeypatch) -> None:
    monkeypatch.delenv("CHAINCOPILOT_LLM_ENABLED", raising=False)
    monkeypatch.delenv("CHAINCOPILOT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    state = load_initial_state()
    event = get_scenario_events("supplier_delay")[0]
    proposal = SupplierAgent().run(state, event)

    assert proposal.llm_used is False
    assert proposal.llm_error is None
    assert proposal.domain_summary == ""
    assert proposal.proposals[0].action_id == "act_supplier_SKU_1_SUP_B"


def test_langgraph_routing_still_works_with_specialist_llm(monkeypatch) -> None:
    from orchestrator.graph import build_graph

    _enable_llm(monkeypatch)

    def _fake_generate_json(self, *, prompt, schema, temperature=0.2):
        if "planner_narrative" in schema.get("properties", {}):
            return {
                "planner_narrative": "Planner narrative",
                "operator_explanation": "Operator explanation",
                "approval_summary": "Approval summary",
            }
        if '"agent": "risk"' in prompt:
            return {
                "domain_summary": "Compound disruption increases risk across sourcing and routing at once.",
                "downstream_impacts": ["Recovery should prioritize service continuity."],
                "recommended_action_ids": [],
                "tradeoffs": ["Aggressive mitigation will raise cost."],
                "notes_for_planner": "Favor cross-domain recovery actions.",
            }
        if '"agent": "supplier"' in prompt:
            return {
                "domain_summary": "Supplier substitution is warranted.",
                "downstream_impacts": ["Primary replenishment reliability is compromised."],
                "recommended_action_ids": ["act_supplier_SKU_1_SUP_B"],
                "tradeoffs": ["Backup suppliers improve reliability at a cost premium."],
                "notes_for_planner": "Use the stronger alternate supplier if score impact is acceptable.",
            }
        if '"agent": "logistics"' in prompt:
            return {
                "domain_summary": "Route risk is elevated.",
                "downstream_impacts": ["Staying on the disrupted lane could slow recovery."],
                "recommended_action_ids": ["act_reroute_SKU_1_R4"],
                "tradeoffs": ["The safer route costs more."],
                "notes_for_planner": "Consider route protection for affected SKUs.",
            }
        return {
            "domain_summary": "Demand impact is manageable.",
            "downstream_impacts": [],
            "recommended_action_ids": [],
            "tradeoffs": [],
            "notes_for_planner": "No additional demand-specific action is required.",
        }

    monkeypatch.setattr("llm.service.GeminiClient.generate_json", _fake_generate_json)

    state = load_initial_state()
    event = get_scenario_events("compound_disruption")[0]
    result = build_graph().invoke(state, event)

    assert result.mode in {Mode.CRISIS, Mode.APPROVAL}
    assert result.latest_plan is not None
    assert result.agent_outputs["risk"].llm_used is True
    assert result.agent_outputs["supplier"].llm_used is True
