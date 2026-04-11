from __future__ import annotations

from agents.base import BaseAgent
from core.models import AgentProposal, Event, SystemState
from llm.service import critique_candidate_plans


class CriticAgent(BaseAgent):
    name = "critic"

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        if state.latest_plan is None or not state.decision_logs:
            proposal.observations.append("no selected plan available for critic review")
            return proposal

        decision_log = state.decision_logs[-1]
        summary, findings, used, error = critique_candidate_plans(
            state=state,
            event=event,
            selected_plan=state.latest_plan,
            evaluations=decision_log.candidate_evaluations,
        )
        state.latest_plan.critic_summary = summary
        decision_log.critic_summary = summary
        decision_log.critic_findings = findings
        decision_log.critic_used = used
        decision_log.critic_error = error

        if summary:
            proposal.domain_summary = summary
            proposal.notes_for_planner = summary
        if findings:
            proposal.downstream_impacts = findings
        proposal.llm_used = used
        proposal.llm_error = error
        proposal.observations.append(
            "critic reviewed candidate plans"
            if used or summary or findings
            else "critic unavailable; deterministic selection retained"
        )
        return proposal
