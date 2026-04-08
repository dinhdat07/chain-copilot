from __future__ import annotations

from agents.base import BaseAgent
from core.enums import ActionType
from core.models import Action, AgentProposal, Event, SystemState


class InventoryAgent(BaseAgent):
    name = "inventory"

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        for sku, item in state.inventory.items():
            projected = item.on_hand + item.incoming_qty - item.forecast_qty
            proposal.observations.append(f"{sku} projected stock: {projected}")
            if projected < item.reorder_point:
                quantity = max(item.reorder_point + item.safety_stock - projected, 0)
                proposal.proposals.append(
                    Action(
                        action_id=f"act_reorder_{sku}",
                        action_type=ActionType.REORDER,
                        target_id=sku,
                        parameters={"quantity": int(quantity)},
                        estimated_cost_delta=quantity * item.unit_cost * 1.05,
                        estimated_service_delta=0.12,
                        estimated_risk_delta=-0.15,
                        estimated_recovery_hours=24.0,
                        reason=f"projected stock for {sku} falls below reorder point",
                        priority=0.8 if projected < item.safety_stock else 0.6,
                    )
                )
        return proposal
