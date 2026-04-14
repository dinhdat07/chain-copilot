from __future__ import annotations

from agents.base import BaseAgent
from core.enums import ActionType, EventType
from core.models import Action, AgentProposal, Event, SystemState


class LogisticsAgent(BaseAgent):
    name = "logistics"
    custom_system_prompt = """You are the Logistics and Routing Agent for a supply chain system.
When transportation routes are blocked or delayed, your responsibility is to find alternative shipping routes that minimize risk, transit time, and cost.
Provide a concise, professional summary (under 4 sentences) of the routing issues, your analysis of alternative routes, and your specific rerouting recommendations.
Write the summary entirely in English. Do NOT use markdown formatting or bullet points in the summary."""

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        blocked_route = event.payload.get("route_id") if event and event.type == EventType.ROUTE_BLOCKAGE else None
        available_routes = [route for route in state.routes.values() if route.status != "blocked"]
        ranked = sorted(available_routes, key=lambda route: (route.risk_score, route.transit_days, route.cost))

        for sku, item in state.inventory.items():
            current_route = state.routes.get(item.preferred_route_id)
            if not current_route:
                continue
            best = ranked[0] if ranked else current_route
            if best.route_id == blocked_route and len(ranked) > 1:
                best = ranked[1]
            if best.route_id != current_route.route_id and (current_route.route_id == blocked_route or best.risk_score < current_route.risk_score):
                proposal.proposals.append(
                    Action(
                        action_id=f"act_reroute_{sku}_{best.route_id}",
                        action_type=ActionType.REROUTE,
                        target_id=sku,
                        parameters={"route_id": best.route_id},
                        estimated_cost_delta=max(best.cost - current_route.cost, 0.0),
                        estimated_service_delta=0.04,
                        estimated_risk_delta=-0.10,
                        estimated_recovery_hours=float(best.transit_days * 8),
                        reason=f"reroute {sku} from {current_route.route_id} to {best.route_id}",
                        priority=0.85 if current_route.route_id == blocked_route else 0.45,
                    )
                )
                proposal.observations.append(f"{sku} reroute candidate: {best.route_id}")
        if event is not None or proposal.proposals:
            route_snapshot = [
                {
                    "route_id": route.route_id,
                    "origin": route.origin,
                    "destination": route.destination,
                    "transit_days": route.transit_days,
                    "cost": route.cost,
                    "risk_score": route.risk_score,
                    "status": route.status,
                }
                for route in ranked
            ]
            self.enrich_with_llm(
                state=state,
                event=event,
                proposal=proposal,
                state_slice={
                    "blocked_route": blocked_route,
                    "route_options": route_snapshot,
                },
            )
        return proposal
