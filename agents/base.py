from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import AgentProposal, Event, SystemState


class BaseAgent(ABC):
    name: str
    custom_system_prompt: str | None = None

    @abstractmethod
    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        raise NotImplementedError

    def enrich_with_llm(
        self,
        *,
        state: SystemState,
        event: Event | None,
        proposal: AgentProposal,
        state_slice: dict,
    ) -> AgentProposal:
        from llm.service import enrich_specialist_proposal

        enrich_specialist_proposal(
            agent_name=self.name,
            state=state,
            event=event,
            proposal=proposal,
            state_slice=state_slice,
            custom_prompt=self.custom_system_prompt,
        )
        return proposal
