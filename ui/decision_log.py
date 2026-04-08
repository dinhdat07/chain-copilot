from __future__ import annotations

import pandas as pd
import streamlit as st

from core.memory import SQLiteStore
from core.models import SystemState
from ui.components import (
    decision_log_dataframe,
    memory_summary_tables,
    rejected_actions_dataframe,
    score_breakdown_dataframe,
)


def render_page(state: SystemState, store: SQLiteStore) -> None:
    st.title("Decision Log")
    if state.decision_logs:
        latest = state.decision_logs[-1]
        st.caption(
            f"Latest decision `{latest.decision_id}` approval status: {latest.approval_status.value}"
        )
        st.subheader("Latest Explanation")
        st.write(latest.rationale)
        st.write(f"Approval required: {latest.approval_required}")
        st.write(f"Approval reason: {latest.approval_reason}")
        st.dataframe(score_breakdown_dataframe(latest), use_container_width=True)
        if latest.winning_factors:
            st.write("Winning factors")
            for factor in latest.winning_factors:
                st.write(f"- {factor}")
        if latest.rejected_actions:
            st.write("Rejected alternatives")
            st.dataframe(rejected_actions_dataframe(latest), use_container_width=True)
    st.subheader("Current Session")
    st.dataframe(decision_log_dataframe(state), use_container_width=True)
    st.subheader("Persisted Logs")
    items = store.list_decision_logs()
    st.dataframe(pd.DataFrame(items), use_container_width=True)
    st.subheader("Learned Memory")
    supplier_df, route_df, scenario_df = memory_summary_tables(state)
    st.write("Supplier reliability")
    st.dataframe(supplier_df, use_container_width=True)
    st.write("Route disruption priors")
    st.dataframe(route_df, use_container_width=True)
    st.write("Scenario outcome history")
    st.dataframe(scenario_df, use_container_width=True)
