from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import AgentProposal, Event, SystemState


class BaseAgent(ABC):
    name: str

    @abstractmethod
    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        raise NotImplementedError
