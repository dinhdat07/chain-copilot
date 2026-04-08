from __future__ import annotations

import streamlit as st

from core.memory import SQLiteStore
from core.models import DecisionLog, SystemState
from ui.components import (
    approval_badge_text,
    decision_log_dataframe,
    memory_summary_tables,
    rejected_actions_dataframe,
    score_breakdown_dataframe,
)


def _render_decision_details(log: DecisionLog) -> None:
    st.write(log.rationale)
    st.write(f"Approval required: {log.approval_required}")
    st.write(f"Approval reason: {log.approval_reason}")
    st.dataframe(score_breakdown_dataframe(log), width="stretch", hide_index=True)
    if log.winning_factors:
        st.write("Winning factors")
        for factor in log.winning_factors:
            st.write(f"- {factor}")
    if log.rejected_actions:
        st.write("Rejected alternatives")
        st.dataframe(rejected_actions_dataframe(log), width="stretch", hide_index=True)


@st.dialog("Persisted Decision Details", width="large")
def _show_persisted_log_dialog(log: DecisionLog) -> None:
    st.caption(f"Decision `{log.decision_id}` | Plan `{log.plan_id}`")
    st.write(approval_badge_text(log))
    _render_decision_details(log)


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
        _render_decision_details(latest)
    else:
        st.info("No decisions are stored yet.")
    st.subheader("Current Session")
    session_df = decision_log_dataframe(state)
    if session_df.empty:
        st.info("Current-session decision history will appear here after the first plan is generated.")
    else:
        st.dataframe(session_df, width="stretch", hide_index=True)
    st.subheader("Persisted Logs")
    items = store.list_decision_logs()
    if items:
        persisted_logs = [DecisionLog.model_validate(item) for item in items]
        header = st.columns([2, 2, 2, 1])
        header[0].markdown("**Decision ID**")
        header[1].markdown("**Plan ID**")
        header[2].markdown("**Approval Status**")
        header[3].markdown("**Action**")
        for log in persisted_logs:
            cols = st.columns([2, 2, 2, 1])
            cols[0].write(log.decision_id)
            cols[1].write(log.plan_id)
            cols[2].write(approval_badge_text(log))
            if cols[3].button("View details", key=f"persisted_{log.decision_id}", width="stretch"):
                _show_persisted_log_dialog(log)
    else:
        st.info("No persisted decision logs yet.")
    st.subheader("Learned Memory")
    supplier_df, route_df, scenario_df = memory_summary_tables(state)
    st.write("Supplier reliability")
    if supplier_df.empty:
        st.info("No supplier learning updates yet.")
    else:
        st.dataframe(supplier_df, width="stretch", hide_index=True)
    st.write("Route disruption priors")
    if route_df.empty:
        st.info("No route-learning updates yet.")
    else:
        st.dataframe(route_df, width="stretch", hide_index=True)
    st.write("Scenario outcome history")
    if scenario_df.empty:
        st.info("No scenario history has been recorded yet.")
    else:
        st.dataframe(scenario_df, width="stretch", hide_index=True)
