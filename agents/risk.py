from __future__ import annotations

from agents.base import BaseAgent
from core.enums import EventType, Mode
from core.models import AgentProposal, Event, SystemState
from policies.modes import select_mode


class RiskAgent(BaseAgent):
    name = "risk"

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        state.mode = select_mode(state, event)
        if event is None:
            proposal.observations.append("no new disruption event")
            return proposal
        proposal.observations.append(f"received {event.type.value} at severity {event.severity:.2f}")
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
                "event_type": event.type.value,
                "event_severity": event.severity,
                "entity_ids": event.entity_ids,
                "payload": event.payload,
                "active_event_count": len(state.active_events),
            },
        )
        return proposal
