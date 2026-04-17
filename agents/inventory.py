from __future__ import annotations

import math
from collections import Counter

from agents.base import BaseAgent
from core.scenario_scope import resolve_scenario_scope
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
    custom_system_prompt = """You are the Inventory Agent for a supply chain control tower.
Explain inventory risk like an operations manager would.
Be specific about stock position, expected demand, days of cover, reorder point, safety stock, and the business impact of inaction.
    If replenishment is proposed, explain why that action is better than waiting.
    Do not invent inventory math, customer orders, or supplier facts that are not in the provided state."""

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        sku_order_counts = Counter(order.sku for order in state.orders)
        risk_rows: list[dict[str, object]] = []
        scope = resolve_scenario_scope(state, event)
        affected_skus = set(scope.affected_skus)
        for sku, item in state.inventory.items():
            if affected_skus and sku not in affected_skus:
                continue
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

            projected = item.on_hand + item.incoming_qty - item.forecast_qty
            daily_demand = max(float(avg_d), 0.0)
            available_stock = item.on_hand + item.incoming_qty
            days_of_cover = (
                available_stock / daily_demand if daily_demand > 0 else float("inf")
            )
            order_count = sku_order_counts.get(sku, 0)
            root_cause = []
            if event is not None:
                root_cause.append(event.type.value.replace("_", " "))
            if lead_time >= 5:
                root_cause.append("long replenishment lead time")
            if reliability < 0.9:
                root_cause.append("below-target supplier reliability")
            if daily_demand > max(item.on_hand, 1):
                root_cause.append("demand running ahead of current on-hand stock")
            cause_text = (
                ", ".join(root_cause) if root_cause else "normal replenishment cycle"
            )

            if projected < item.safety_stock:
                inventory_status = "stockout risk"
            elif projected < item.reorder_point:
                inventory_status = "reorder risk"
            elif available_stock > max(item.reorder_point * 1.8, daily_demand * 10):
                inventory_status = "overstock"
            else:
                inventory_status = "stable"

            risk_rows.append(
                {
                    "sku": sku,
                    "name": item.name,
                    "inventory_status": inventory_status,
                    "on_hand": item.on_hand,
                    "incoming_qty": item.incoming_qty,
                    "forecast_qty": item.forecast_qty,
                    "projected_stock": projected,
                    "reorder_point": item.reorder_point,
                    "safety_stock": item.safety_stock,
                    "days_of_cover": None
                    if days_of_cover == float("inf")
                    else round(days_of_cover, 1),
                    "lead_time_days": lead_time,
                    "supplier_reliability": reliability,
                    "pending_orders": order_count,
                    "root_cause": cause_text,
                }
            )

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
        ranked_rows = sorted(
            risk_rows,
            key=lambda row: (
                0
                if row["inventory_status"] == "stockout risk"
                else 1
                if row["inventory_status"] == "reorder risk"
                else 2,
                row["days_of_cover"] if row["days_of_cover"] is not None else 9999,
            ),
        )
        critical_rows = [
            row
            for row in ranked_rows
            if row["inventory_status"] in {"stockout risk", "reorder risk"}
        ]
        if critical_rows:
            top = critical_rows[0]
            pending_orders = int(top["pending_orders"])
            order_text = (
                f" and may affect {pending_orders} pending customer orders"
                if pending_orders
                else ""
            )
            coverage_text = (
                f"{top['days_of_cover']:.1f} days of cover"
                if top["days_of_cover"] is not None
                else "limited demand visibility"
            )
            proposal.domain_summary = (
                f"Inventory pressure is concentrated on {top['name']} ({top['sku']}) within the direct disruption scope. "
                f"Projected stock falls to {int(top['projected_stock'])} units versus a reorder point of {int(top['reorder_point'])} "
                f"and safety stock of {int(top['safety_stock'])}. At the current demand pace, that leaves {coverage_text}. "
                f"The main driver is {top['root_cause']}; if no action is taken, stock availability could tighten within the next replenishment cycle{order_text}."
            )
            proposal.risks.append(
                f"{len(critical_rows)} SKUs are below reorder point; {sum(1 for row in critical_rows if row['inventory_status'] == 'stockout risk')} are already below safety stock."
            )
            for row in critical_rows[:3]:
                coverage_text = (
                    f"{row['days_of_cover']:.1f} days of cover"
                    if row["days_of_cover"] is not None
                    else "no reliable cover estimate"
                )
                proposal.downstream_impacts.append(
                    f"{row['sku']} is in {row['inventory_status']} with projected stock {int(row['projected_stock'])}, reorder point {int(row['reorder_point'])}, and {coverage_text}."
                )
            proposal.tradeoffs.append(
                "Replenishing now protects service continuity but increases near-term inventory and working-capital cost."
            )
            proposal.notes_for_planner = (
                f"Prioritize SKUs already below safety stock or with fewer than "
                f"{critical_rows[0]['days_of_cover'] or 0:.1f} days of cover."
            )
        elif ranked_rows:
            stable_count = sum(
                1 for row in ranked_rows if row["inventory_status"] == "stable"
            )
            proposal.domain_summary = f"Inventory is broadly stable. {stable_count} SKUs remain above reorder point after applying current demand, lead time, and safety stock assumptions."
            proposal.tradeoffs.append(
                "Holding current inventory avoids unnecessary replenishment cost, but coverage should still be refreshed as demand and supplier conditions change."
            )
            proposal.notes_for_planner = "No urgent inventory-led intervention is required; keep the plan efficiency-focused."

        if event is not None or proposal.proposals:
            self.enrich_with_llm(
                state=state,
                event=event,
                proposal=proposal,
                state_slice={
                    "scenario_scope": scope.to_dict(),
                    "inventory_focus": ranked_rows[:5],
                    "critical_sku_count": len(critical_rows),
                    "proposed_reorders": [
                        {
                            "action_id": action.action_id,
                            "target_id": action.target_id,
                            "quantity": action.parameters.get("quantity"),
                            "reason": action.reason,
                            "estimated_cost_delta": action.estimated_cost_delta,
                            "estimated_service_delta": action.estimated_service_delta,
                            "estimated_risk_delta": action.estimated_risk_delta,
                        }
                        for action in proposal.proposals[:5]
                    ],
                },
            )
        return proposal
