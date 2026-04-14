from __future__ import annotations

from collections import defaultdict

from agents.base import BaseAgent
from core.enums import ActionType, EventType
from core.models import Action, AgentProposal, Event, SystemState


class SupplierAgent(BaseAgent):
    name = "supplier"
    custom_system_prompt = """You are the Supplier Management Agent for a supply chain system.
When supplier delays or disruptions occur, your job is to analyze alternative suppliers, factoring in reliability, cost, and lead times.
Provide a concise, professional summary (under 4 sentences) of the supplier issues, your evaluation of the alternatives, and the recommended supplier switch.
Write the summary entirely in English. Do NOT use markdown formatting or bullet points in the summary."""

    def run(self, state: SystemState, event: Event | None = None) -> AgentProposal:
        proposal = AgentProposal(agent=self.name)
        by_sku: dict[str, list] = defaultdict(list)
        for supplier in state.suppliers.values():
            by_sku[supplier.sku].append(supplier)

        delayed_supplier = (
            event.payload.get("supplier_id")
            if event and event.type == EventType.SUPPLIER_DELAY
            else None
        )
        for sku, item in state.inventory.items():
            current = item.preferred_supplier_id
            current_supplier = state.suppliers.get(f"{current}_{sku}")
            if current_supplier is None:
                current_supplier = state.suppliers.get(current)
            ranked = sorted(
                by_sku.get(sku, []),
                key=lambda supplier: (
                    -supplier.reliability,
                    supplier.unit_cost,
                    supplier.lead_time_days,
                ),
            )
            if not ranked:
                proposal.risks.append(f"no suppliers available for {sku}")
                continue
            best = ranked[0]
            if best.supplier_id == delayed_supplier and len(ranked) > 1:
                best = ranked[1]
            if current_supplier and best.supplier_id != current_supplier.supplier_id:
                cost_delta = best.unit_cost - current_supplier.unit_cost
                proposal.proposals.append(
                    Action(
                        action_id=f"act_supplier_{sku}_{best.supplier_id}",
                        action_type=ActionType.SWITCH_SUPPLIER,
                        target_id=sku,
                        parameters={"supplier_id": best.supplier_id},
                        estimated_cost_delta=max(
                            cost_delta * max(item.forecast_qty, 1), 0.0
                        ),
                        estimated_service_delta=0.06
                        if best.reliability >= current_supplier.reliability
                        else 0.02,
                        estimated_risk_delta=-0.12
                        if best.supplier_id != delayed_supplier
                        else -0.02,
                        estimated_recovery_hours=float(best.lead_time_days * 12),
                        reason=f"switch {sku} from {current_supplier.supplier_id} to {best.supplier_id}",
                        priority=0.9
                        if delayed_supplier == current_supplier.supplier_id
                        else 0.55,
                    )
                )
                proposal.observations.append(
                    f"{sku} best supplier candidate: {best.supplier_id}"
                )
        if event is not None or proposal.proposals:
            supplier_snapshot = {
                sku: [
                    {
                        "supplier_id": supplier.supplier_id,
                        "unit_cost": supplier.unit_cost,
                        "lead_time_days": supplier.lead_time_days,
                        "reliability": supplier.reliability,
                        "status": supplier.status,
                    }
                    for supplier in ranked_suppliers
                ]
                for sku, ranked_suppliers in by_sku.items()
            }
            self.enrich_with_llm(
                state=state,
                event=event,
                proposal=proposal,
                state_slice={
                    "delayed_supplier": delayed_supplier,
                    "supplier_options": supplier_snapshot,
                },
            )
        return proposal
