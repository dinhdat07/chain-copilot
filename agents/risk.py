from __future__ import annotations

import requests

from agents.base import BaseAgent
from core.models import AgentProposal, Event, SystemState
from policies.modes import select_mode


class RiskAgent(BaseAgent):
    name = "risk"

    custom_system_prompt = (
        "Role: {agent_name} specialist agent in an autonomous supply chain control tower. "
        "CRITICAL: Your ONLY goal is to write a comprehensive 'domain_summary' in English "
        "summarizing the disruption based on external_api_data. "
        "Make it sound natural but precise. Do not invent new actions or make up false information. "
        "Return empty arrays for impacts, tradeoffs, and recommended actions."
    )

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        state.mode = select_mode(state, event)
        api_payloads = {}
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
                f"{', '.join(event.entity_ids) if event.entity_ids else 'the network'}."
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


