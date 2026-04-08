from __future__ import annotations

import pandas as pd
import streamlit as st

from core.models import DecisionLog, Plan, SystemState


def render_kpis(state: SystemState) -> None:
    cols = st.columns(5)
    cols[0].metric("Service Level", f"{state.kpis.service_level:.1%}")
    cols[1].metric("Total Cost", f"{state.kpis.total_cost:,.0f}")
    cols[2].metric("Disruption Risk", f"{state.kpis.disruption_risk:.1%}")
    cols[3].metric("Recovery Speed", f"{state.kpis.recovery_speed:.1%}")
    cols[4].metric("Stockout Risk", f"{state.kpis.stockout_risk:.1%}")


def inventory_dataframe(state: SystemState) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sku": item.sku,
                "on_hand": item.on_hand,
                "incoming_qty": item.incoming_qty,
                "forecast_qty": item.forecast_qty,
                "preferred_supplier_id": item.preferred_supplier_id,
                "preferred_route_id": item.preferred_route_id,
            }
            for item in state.inventory.values()
        ]
    )


def decision_log_dataframe(state: SystemState) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "decision_id": log.decision_id,
                "plan_id": log.plan_id,
                "approval_required": log.approval_required,
                "approval_reason": log.approval_reason,
                "approval_status": log.approval_status.value,
                "service_level_after": log.after_kpis.service_level,
                "total_cost_after": log.after_kpis.total_cost,
                "rationale": log.rationale,
            }
            for log in reversed(state.decision_logs)
        ]
    )


def kpi_comparison_dataframe(decision_log: DecisionLog) -> pd.DataFrame:
    before = decision_log.before_kpis
    after = decision_log.after_kpis
    return pd.DataFrame(
        [
            {
                "metric": "service_level",
                "before": before.service_level,
                "after": after.service_level,
                "delta": round(after.service_level - before.service_level, 4),
            },
            {
                "metric": "total_cost",
                "before": before.total_cost,
                "after": after.total_cost,
                "delta": round(after.total_cost - before.total_cost, 2),
            },
            {
                "metric": "disruption_risk",
                "before": before.disruption_risk,
                "after": after.disruption_risk,
                "delta": round(after.disruption_risk - before.disruption_risk, 4),
            },
            {
                "metric": "recovery_speed",
                "before": before.recovery_speed,
                "after": after.recovery_speed,
                "delta": round(after.recovery_speed - before.recovery_speed, 4),
            },
        ]
    )


def plan_actions_dataframe(plan: Plan) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "action_id": action.action_id,
                "type": action.action_type.value,
                "target_id": action.target_id,
                "estimated_cost_delta": action.estimated_cost_delta,
                "estimated_risk_delta": action.estimated_risk_delta,
                "estimated_recovery_hours": action.estimated_recovery_hours,
                "reason": action.reason,
            }
            for action in plan.actions
        ]
    )


def score_breakdown_dataframe(decision_log: DecisionLog) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"component": component, "contribution": contribution}
            for component, contribution in decision_log.score_breakdown.items()
        ]
    )


def rejected_actions_dataframe(decision_log: DecisionLog) -> pd.DataFrame:
    return pd.DataFrame(decision_log.rejected_actions)


def memory_summary_tables(state: SystemState) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    memory = state.memory
    supplier_rows = []
    route_rows = []
    scenario_rows = []
    if memory:
        supplier_rows = [
            {"supplier_id": supplier_id, "learned_reliability": reliability}
            for supplier_id, reliability in memory.supplier_reliability.items()
        ]
        route_rows = [
            {"route_id": route_id, "disruption_prior": prior}
            for route_id, prior in memory.route_disruption_priors.items()
        ]
        scenario_rows = [
            {
                "scenario_id": scenario_id,
                "runs": details.get("runs", 0),
                "latest_run_id": details.get("latest_run_id"),
                "latest_plan_id": details.get("latest_plan_id"),
                "latest_approval_status": details.get("latest_approval_status"),
            }
            for scenario_id, details in memory.scenario_outcomes.items()
        ]
    return (
        pd.DataFrame(supplier_rows),
        pd.DataFrame(route_rows),
        pd.DataFrame(scenario_rows),
    )
