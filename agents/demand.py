from __future__ import annotations

from collections import defaultdict

import pandas as pd

from agents.base import BaseAgent
from core.scenario_scope import payload_demand_changes, resolve_scenario_scope
from core.enums import ActionType, EventType
from core.models import Action, AgentProposal, Event, SystemState


class DemandAgent(BaseAgent):
    name = "demand"
    custom_system_prompt = """You are the Demand Agent for a supply chain management system.
Your role is to analyze demand spikes, historical demand patterns, and forecast future demand.
When a disruption or event occurs (like a DEMAND_SPIKE), you evaluate how it impacts the required inventory levels.
    Provide a concise, professional summary (under 4 sentences) of your demand analysis, the specific SKU affected, and your recommendations.
    Write the summary entirely in English. Do NOT use markdown formatting or bullet points in the summary."""

    @staticmethod
    def _event_demand_changes(event: Event | None) -> dict[str, float]:
        if event is None:
            return {}
        if event.type not in {EventType.DEMAND_SPIKE, EventType.COMPOUND}:
            return {}
        return {
            str(item["sku"]): float(item.get("multiplier", 1.0))
            for item in payload_demand_changes(event)
        }

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        grouped: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for demand in state.demands:
            grouped[demand.sku].append((demand.day_index, demand.quantity))

        event_changes = self._event_demand_changes(event)
        scope = resolve_scenario_scope(state, event)
        affected_skus = set(scope.demand_affected_skus or event_changes)
        for sku, multiplier in event_changes.items():
            proposal.observations.append(
                f"{sku} demand spike multiplier applied: {multiplier:.2f}"
            )

        for sku, points in grouped.items():
            if affected_skus and sku not in affected_skus:
                continue
            df = pd.DataFrame(points, columns=["day_index", "quantity"]).sort_values(
                "day_index"
            )
            df_30 = df.tail(30)

            avg_d = df_30["quantity"].mean()
            std_d = df_30["quantity"].std()

            forecast = int(round(avg_d)) if pd.notna(avg_d) else 0
            std_d_val = float(std_d) if pd.notna(std_d) else 0.0

            if sku in event_changes:
                forecast = int(round(forecast * event_changes[sku]))
            if sku in state.inventory:
                state.inventory[sku].forecast_qty = max(0, forecast)
                state.inventory[sku].std_demand = std_d_val
                proposal.observations.append(
                    f"{sku} historical demand (30 days): Avg = {forecast}, Std Dev = {std_d_val:.2f}"
                )

        if event and event.type in {EventType.DEMAND_SPIKE, EventType.COMPOUND}:
            for event_sku in affected_skus:
                if event_sku not in state.inventory:
                    continue
                item = state.inventory[event_sku]
                proposal.proposals.append(
                    Action(
                        action_id=f"act_demand_rebalance_{event_sku}",
                        action_type=ActionType.REBALANCE,
                        target_id=event_sku,
                        parameters={
                            "quantity": max(item.forecast_qty - item.on_hand, 0)
                        },
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
            if not affected_skus or sku in affected_skus
        }
        if event is not None or proposal.proposals:
            self.enrich_with_llm(
                state=state,
                event=event,
                proposal=proposal,
                state_slice={
                    "event_skus": sorted(affected_skus),
                    "demand_changes": event_changes,
                    "scenario_scope": scope.to_dict(),
                    "affected_inventory": affected_inventory,
                },
            )
        return proposal
