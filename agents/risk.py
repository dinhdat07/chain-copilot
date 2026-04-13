from __future__ import annotations

import requests

from agents.base import BaseAgent
from core.enums import EventType, Mode
from core.models import AgentProposal, Event, SystemState
from policies.modes import select_mode


class RiskAgent(BaseAgent):
    name = "risk"

    custom_system_prompt = (
        "Role: {agent_name} specialist agent in an autonomous supply chain control tower. "
        "CRITICAL: Write the 'domain_summary' in English summarizing the disruption based on external_api_data"
        "Make it sound natural but precise. Do not invent new actions or make up false information."
    )

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        state.mode = select_mode(state, event)
        api_payloads = {}

        # 1. Fetch Weather API
        try:
            weather_res = requests.get(
                "http://localhost:8000/api/v1/mock/weather", timeout=5
            ).json()
            api_payloads["weather"] = weather_res
        except Exception as e:
            api_payloads["weather"] = {"error": "API failed"}

        # 2. Fetch Routes API
        try:
            routes_res = requests.get(
                "http://localhost:8000/api/v1/mock/routes", timeout=5
            ).json()
            api_payloads["routes"] = routes_res
        except Exception as e:
            api_payloads["routes"] = {"error": "API failed"}

        # 3. Fetch Suppliers API
        try:
            suppliers_res = requests.get(
                "http://localhost:8000/api/v1/mock/suppliers", timeout=5
            ).json()
            api_payloads["suppliers"] = suppliers_res
        except Exception as e:
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
        return proposal
