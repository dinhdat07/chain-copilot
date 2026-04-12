from __future__ import annotations

import requests

from agents.base import BaseAgent
from core.enums import EventType, Mode
from core.models import AgentProposal, Event, SystemState
from policies.modes import select_mode


class RiskAgent(BaseAgent):
    name = "risk"

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

        # Perform basic heuristic analysis to populate observations (LLM will do deeper analysis)
        weather_main = (
            api_payloads["weather"].get("weather", [{}])[0].get("main", "Unknown")
        )
        if weather_main not in ["Clear", "Unknown"]:
            desc = (
                api_payloads["weather"]
                .get("weather", [{}])[0]
                .get("description", weather_main)
            )
            proposal.observations.append(f"Weather Alert: {desc}")
            proposal.risks.append("adverse weather conditions")

        routes_data = api_payloads["routes"].get("routes", [])
        blocked = [
            r.get("route_id") for r in routes_data if r.get("status") == "Blocked"
        ]
        if blocked:
            proposal.observations.append(
                f"Route Blockage: {', '.join(filter(None, blocked))} reported blocked."
            )
            proposal.risks.append("transportation routes compromised")
            if state.mode == Mode.NORMAL:
                state.mode = Mode.CRISIS

        suppliers_data = api_payloads["suppliers"].get("vendors", [])
        delayed = [
            s.get("vendor_id")
            for s in suppliers_data
            if s.get("overall_status") == "Delayed"
        ]
        if delayed:
            proposal.observations.append(
                f"Supplier Delay: {', '.join(filter(None, delayed))} reported delays."
            )
            proposal.risks.append("supplier lead time disrupted")

        if event is None and not proposal.observations:
            proposal.observations.append(
                "no new disruption event and APIs report normal status"
            )
            return proposal

        if event is not None:
            proposal.observations.append(
                f"received {event.type.value} at severity {event.severity:.2f}"
            )
            if event.type == EventType.COMPOUND:
                proposal.risks.append("compound disruption detected")
                state.mode = Mode.CRISIS
            if event.severity >= 0.75:
                proposal.risks.append("high severity disruption")

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
