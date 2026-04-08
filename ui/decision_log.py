from __future__ import annotations

import pandas as pd
import streamlit as st

from core.memory import SQLiteStore
from core.models import SystemState
from ui.components import (
    approval_badge_text,
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
            f"Latest decision `{latest.decision_id}` | {approval_badge_text(latest)}"
        )
        st.write(f"Latest plan: `{latest.plan_id}`")
        if state.pending_plan:
            st.warning("A plan is still pending approval. Resolve it before running new plans or scenarios.")
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
    else:
        st.info("No decisions are stored yet.")
    st.subheader("Current Session")
    session_df = decision_log_dataframe(state)
    if session_df.empty:
        st.info("Current-session decision history will appear here after the first plan is generated.")
    else:
        st.dataframe(session_df, use_container_width=True, hide_index=True)
    st.subheader("Persisted Logs")
    items = store.list_decision_logs()
    if items:
        st.dataframe(pd.DataFrame(items), use_container_width=True)
    else:
        st.info("No persisted decision logs yet.")
    st.subheader("Learned Memory")
    supplier_df, route_df, scenario_df = memory_summary_tables(state)
    st.write("Supplier reliability")
    if supplier_df.empty:
        st.info("No supplier learning updates yet.")
    else:
        st.dataframe(supplier_df, use_container_width=True, hide_index=True)
    st.write("Route disruption priors")
    if route_df.empty:
        st.info("No route-learning updates yet.")
    else:
        st.dataframe(route_df, use_container_width=True, hide_index=True)
    st.write("Scenario outcome history")
    if scenario_df.empty:
        st.info("No scenario history has been recorded yet.")
    else:
        st.dataframe(scenario_df, use_container_width=True, hide_index=True)
