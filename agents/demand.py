from __future__ import annotations

from collections import defaultdict

import pandas as pd

from agents.base import BaseAgent
from core.enums import ActionType, EventType
from core.models import Action, AgentProposal, Event, SystemState


class DemandAgent(BaseAgent):
    name = "demand"

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        grouped: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for order in state.orders:
            grouped[order.sku].append((order.day_index, order.quantity))

        multiplier = 1.0
        event_sku = None
        if event and event.type == EventType.DEMAND_SPIKE:
            multiplier = float(event.payload.get("multiplier", 1.5))
            event_sku = event.payload.get("sku")
            proposal.observations.append(f"demand spike multiplier applied: {multiplier:.2f}")

        for sku, points in grouped.items():
            df = pd.DataFrame(points, columns=["day_index", "quantity"]).sort_values("day_index")
            rolling = df["quantity"].tail(3).mean()
            forecast = int(round(rolling if not pd.isna(rolling) else df["quantity"].mean()))
            if sku == event_sku:
                forecast = int(round(forecast * multiplier))
            if sku in state.inventory:
                state.inventory[sku].forecast_qty = max(0, forecast)
                proposal.observations.append(f"{sku} forecast set to {forecast}")

        if event and event.type == EventType.DEMAND_SPIKE and event_sku in state.inventory:
            item = state.inventory[event_sku]
            proposal.proposals.append(
                Action(
                    action_id=f"act_demand_rebalance_{event_sku}",
                    action_type=ActionType.REBALANCE,
                    target_id=event_sku,
                    parameters={"quantity": max(item.forecast_qty - item.on_hand, 0)},
                    estimated_cost_delta=40.0,
                    estimated_service_delta=0.08,
                    estimated_risk_delta=-0.10,
                    estimated_recovery_hours=8.0,
                    reason=f"pre-position stock for {event_sku} demand spike",
                    priority=0.75,
                )
            )

        affected_inventory = {
            sku: {
                "on_hand": item.on_hand,
                "incoming_qty": item.incoming_qty,
                "forecast_qty": item.forecast_qty,
                "reorder_point": item.reorder_point,
                "safety_stock": item.safety_stock,
            }
            for sku, item in state.inventory.items()
            if event_sku is None or sku == event_sku
        }
        if event is not None or proposal.proposals:
            self.enrich_with_llm(
                state=state,
                event=event,
                proposal=proposal,
                state_slice={
                    "event_sku": event_sku,
                    "multiplier": multiplier,
                    "affected_inventory": affected_inventory,
                },
            )
        return proposal
