from __future__ import annotations

import math

from agents.base import BaseAgent
from core.enums import ActionType
from core.models import Action, AgentProposal, Event, SystemState


def approximate_z_score(service_level: float) -> float:
    """Approximation of the inverse CDF of the normal distribution."""
    p = max(0.5001, min(0.9999, service_level))
    t = math.sqrt(-2.0 * math.log(1.0 - p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    z = t - ((c2 * t + c1) * t + c0) / (((d3 * t + d2) * t + d1) * t + 1.0)
    return max(0.0, z)


class InventoryAgent(BaseAgent):
    name = "inventory"

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        for sku, item in state.inventory.items():
            # --- 1. Calculate parameters from Demand and Supplier ---
            avg_d = item.forecast_qty
            std_d = getattr(item, "std_demand", 0.0)

            supplier_key = f"{item.preferred_supplier_id}_{sku}"
            supplier = state.suppliers.get(supplier_key)

            lead_time = supplier.lead_time_days if supplier else 0
            reliability = supplier.reliability if supplier else 0.95

            z_score = approximate_z_score(reliability)

            # --- 2. Calculate LTD, SS, ROP ---
            ltd = avg_d * lead_time
            ss = z_score * std_d * math.sqrt(lead_time) if lead_time > 0 else 0.0
            rop = ltd + ss

            # --- 3. Save back to InventoryItem ---
            item.reorder_point = int(round(rop))
            item.safety_stock = int(round(ss))

            proposal.observations.append(
                f"{sku}: Lead Time={lead_time}d, Z={z_score:.2f} (Rel={reliability:.2f}). "
                f"LTD={ltd:.1f}, SS={ss:.1f}, new ROP={item.reorder_point}"
            )

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
                        reason=f"projected stock ({projected}) for {sku} falls below ROP ({item.reorder_point})",
                        priority=0.8 if projected < item.safety_stock else 0.6,
                    )
                )
        return proposal
