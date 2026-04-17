from __future__ import annotations

import requests

from agents.base import BaseAgent
from core.scenario_scope import direct_scope_summary, resolve_scenario_scope
from core.models import AgentProposal, Event, SystemState
from policies.modes import select_mode


class RiskAgent(BaseAgent):
    name = "risk"

    custom_system_prompt = (
        "Role: {agent_name} specialist agent in an autonomous supply chain control tower. "
        "CRITICAL: Your ONLY goal is to write a comprehensive 'domain_summary' in English "
        "summarizing the disruption for the declared scenario scope first, then only mention external_api_data that is directly relevant to those affected entities. "
        "Do not broaden the blast radius beyond scenario_scope. Do not mention unrelated suppliers, routes, or regions just because they appear in external_api_data. "
        "If external_api_data is generic or not directly tied to the affected SKUs, treat it as background context and keep the summary centered on scenario_scope. "
        "Make it sound natural but precise. Do not invent new actions or make up false information. "
        "Return empty arrays for impacts, tradeoffs, and recommended actions."
    )

    @staticmethod
    def _scenario_brief(event: Event | None, scenario_scope: dict[str, object]) -> str:
        if event is None:
            return "No active disruption."
        affected_skus = scenario_scope.get("affected_skus", [])
        route_ids = scenario_scope.get("route_ids", [])
        supplier_ids = scenario_scope.get("supplier_ids", [])
        if event.type.value == "supplier_delay":
            delay_hours = event.payload.get("delay_hours")
            return (
                f"Primary scenario: supplier delay at {', '.join(supplier_ids) or 'an unspecified supplier'} with a declared delay of {delay_hours} hours "
                f"affecting SKUs {', '.join(affected_skus) if affected_skus else 'not specified'}."
            )
        if event.type.value == "demand_spike":
            changes = scenario_scope.get("demand_changes", [])
            change_text = ", ".join(
                f"{item.get('sku')} x{float(item.get('multiplier', 1.0)):.1f}"
                for item in changes
                if isinstance(item, dict) and item.get("sku")
            )
            return (
                "Primary scenario: demand spike affecting only the declared SKU set"
                f" ({change_text or ', '.join(affected_skus)})."
            )
        if event.type.value == "route_blockage":
            return (
                f"Primary scenario: route blockage on {', '.join(route_ids) or 'the declared lanes'} "
                f"directly affecting SKUs {', '.join(affected_skus) if affected_skus else 'derived from current route dependencies'}."
            )
        if event.type.value == "compound":
            return (
                f"Primary scenario: compound disruption across routes {', '.join(route_ids) or 'none declared'} "
                f"and suppliers {', '.join(supplier_ids) or 'none declared'}, with direct impact on "
                f"{', '.join(affected_skus) if affected_skus else 'the declared entities'}."
            )
        return (
            f"Primary scenario: {event.type.value.replace('_', ' ')} affecting "
            f"{', '.join(affected_skus) if affected_skus else 'the declared entities'}."
        )

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        state.mode = select_mode(state, event)
        api_payloads = {}
        resolved_scope = resolve_scenario_scope(state, event)
        scenario_scope = resolved_scope.to_dict()
        scenario_brief = self._scenario_brief(event, scenario_scope)
        if event is None:
            proposal.observations.append(
                f"Network operating in {state.mode.value} mode with no active trigger event"
            )
            proposal.domain_summary = (
                f"Risk review completed with no incoming disruption. Current operating mode is {state.mode.value}."
            )
        else:
            proposal.observations.append(
                f"{event.type.value.replace('_', ' ')} detected at severity {event.severity:.2f}"
            )
            proposal.risks.append(
                f"Mode switched to {state.mode.value} because disruption severity requires closer monitoring"
            )
            proposal.domain_summary = (
                f"{event.type.value.replace('_', ' ').title()} requires risk review for "
                f"{', '.join(event.entity_ids) if event.entity_ids else 'the network'}. "
                f"{direct_scope_summary(resolved_scope)}"
            )

        # 1. Fetch Weather API
        try:
            weather_res = requests.get(
                "http://localhost:8000/api/v1/mock/weather", timeout=5
            ).json()
            api_payloads["weather"] = weather_res
        except Exception:
            api_payloads["weather"] = {"error": "API failed"}

        # 2. Fetch Routes API
        try:
            routes_res = requests.get(
                "http://localhost:8000/api/v1/mock/routes", timeout=5
            ).json()
            api_payloads["routes"] = routes_res
        except Exception:
            api_payloads["routes"] = {"error": "API failed"}

        # 3. Fetch Suppliers API
        try:
            suppliers_res = requests.get(
                "http://localhost:8000/api/v1/mock/suppliers", timeout=5
            ).json()
            api_payloads["suppliers"] = suppliers_res
        except Exception:
            api_payloads["suppliers"] = {"error": "API failed"}

        self.enrich_with_llm(
            state=state,
            event=event,
            proposal=proposal,
            state_slice={
                "selected_mode": state.mode.value,
                "event_type": event.type.value if event else "none",
                "event_severity": event.severity if event else 0.0,
                "entity_ids": event.entity_ids if event else [],
                "payload": event.payload if event else {},
                "scenario_scope": scenario_scope,
                "scenario_brief": scenario_brief,
                "active_event_count": len(state.active_events),
                "external_api_data": api_payloads,
            },
        )

        if not proposal.downstream_impacts and event is not None:
            proposal.downstream_impacts.append(
                "Elevated disruption risk may affect downstream service level and recovery speed."
            )

        # Keep the risk agent non-prescriptive even when the LLM returns extras.
        proposal.recommended_action_ids.clear()
        proposal.tradeoffs.clear()

        return proposal
