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
        for demand in state.demands:
            grouped[demand.sku].append((demand.day_index, demand.quantity))

        multiplier = 1.0
        event_sku = None
        if event and event.type == EventType.DEMAND_SPIKE:
            multiplier = float(event.payload.get("multiplier", 1.5))
            event_sku = event.payload.get("sku")
            proposal.observations.append(
                f"demand spike multiplier applied: {multiplier:.2f}"
            )

        for sku, points in grouped.items():
            df = pd.DataFrame(points, columns=["day_index", "quantity"]).sort_values(
                "day_index"
            )
            df_30 = df.tail(30)

            avg_d = df_30["quantity"].mean()
            std_d = df_30["quantity"].std()

            forecast = int(round(avg_d)) if pd.notna(avg_d) else 0
            std_d_val = float(std_d) if pd.notna(std_d) else 0.0

            if sku == event_sku:
                forecast = int(round(forecast * multiplier))
            if sku in state.inventory:
                state.inventory[sku].forecast_qty = max(0, forecast)
                state.inventory[sku].std_demand = std_d_val
                proposal.observations.append(
                    f"{sku} historical demand (30 days): Avg = {forecast}, Std Dev = {std_d_val:.2f}"
                )

        if (
            event
            and event.type == EventType.DEMAND_SPIKE
            and event_sku in state.inventory
        ):
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
