from __future__ import annotations

from agents.base import BaseAgent
from core.scenario_scope import payload_route_ids, resolve_scenario_scope
from core.enums import ActionType
from core.models import Action, AgentProposal, Event, SystemState


class LogisticsAgent(BaseAgent):
    name = "logistics"
    custom_system_prompt = """You are the Logistics and Routing Agent for a supply chain system.
When transportation routes are blocked or delayed, your responsibility is to find alternative shipping routes that minimize risk, transit time, and cost.
Provide a concise, professional summary (under 4 sentences) of the routing issues, your analysis of alternative routes, and your specific rerouting recommendations.
Write the summary entirely in English. Do NOT use markdown formatting or bullet points in the summary."""

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        scope = resolve_scenario_scope(state, event)
        blocked_routes = set(payload_route_ids(event))
        affected_skus = set(scope.route_affected_skus)
        available_routes = [
            route
            for route in state.routes.values()
            if route.status != "blocked" and route.route_id not in blocked_routes
        ]

        for sku, item in state.inventory.items():
            if affected_skus and sku not in affected_skus:
                continue
            current_route = state.routes.get(item.preferred_route_id)
            if not current_route:
                continue
            if blocked_routes and current_route.route_id not in blocked_routes:
                continue

            valid_routes = [
                r
                for r in available_routes
                if r.destination == current_route.destination
                and r.origin == current_route.origin
            ]
            ranked = sorted(
                valid_routes,
                key=lambda route: (route.risk_score, route.transit_days, route.cost),
            )

            best = ranked[0] if ranked else None
            if best is not None and best.route_id != current_route.route_id:
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
                        priority=0.85,
                    )
                )
                proposal.observations.append(
                    f"{sku} reroute candidate: {best.route_id}"
                )

        ranked_all = sorted(
            available_routes,
            key=lambda route: (route.risk_score, route.transit_days, route.cost),
        )
        if blocked_routes:
            proposal.domain_summary = (
                f"Routing disruption is limited to {len(blocked_routes)} blocked lane(s), "
                f"directly exposing {len(affected_skus)} SKU(s) across {len(scope.warehouse_ids)} warehouse(s). "
                f"Only those directly exposed SKUs were evaluated for reroute recovery."
            )
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
                for route in ranked_all
            ]
            self.enrich_with_llm(
                state=state,
                event=event,
                proposal=proposal,
                state_slice={
                    "blocked_routes": sorted(blocked_routes),
                    "scenario_scope": scope.to_dict(),
                    "route_options": route_snapshot,
                },
            )
        return proposal
