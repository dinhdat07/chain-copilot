from __future__ import annotations

import pandas as pd
import streamlit as st

from core.models import SystemState


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
                "approval_status": log.approval_status.value,
                "service_level_after": log.after_kpis.service_level,
                "total_cost_after": log.after_kpis.total_cost,
                "rationale": log.rationale,
            }
            for log in reversed(state.decision_logs)
        ]
    )
