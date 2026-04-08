from __future__ import annotations

from agents.base import BaseAgent
from core.enums import ActionType, EventType
from core.models import Action, AgentProposal, Event, SystemState


class LogisticsAgent(BaseAgent):
    name = "logistics"

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
        return proposal
