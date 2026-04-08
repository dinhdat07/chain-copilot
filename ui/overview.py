from __future__ import annotations

import streamlit as st

from core.memory import SQLiteStore
from core.models import SystemState
from orchestrator.service import approve_pending_plan, request_safer_plan, run_daily_plan
from ui.components import (
    demo_flow_dataframe,
    event_feed_dataframe,
    inventory_dataframe,
    kpi_comparison_dataframe,
    mode_summary,
    plan_actions_dataframe,
    render_kpis,
    selected_action_summary,
)

def render_page(state: SystemState, store: SQLiteStore) -> SystemState:
    updated_state = state
    st.title("Overview")
    is_blocked = updated_state.pending_plan is not None
    summary = mode_summary(updated_state)
    action_col, mode_col = st.columns([1, 2])
    if action_col.button("Run daily plan", use_container_width=True, disabled=is_blocked):
        updated_state = run_daily_plan(state, store)
        st.session_state["app_state"] = updated_state
        st.rerun()
    mode_col.caption(f"{summary['label']} | {summary['message']}")

    tone = summary["tone"]
    if tone == "success":
        st.success(summary["message"])
    elif tone == "warning":
        st.warning(summary["message"])
    else:
        st.error(summary["message"])

    render_kpis(updated_state)

    st.subheader("Guided Demo Flow")
    st.dataframe(demo_flow_dataframe(updated_state), use_container_width=True, hide_index=True)

    if updated_state.decision_logs:
        latest_decision = updated_state.decision_logs[-1]
        st.subheader("Baseline vs Selected Plan")
        st.dataframe(kpi_comparison_dataframe(latest_decision), use_container_width=True)

    if updated_state.latest_plan:
        st.subheader("Latest Plan")
        plan = updated_state.latest_plan
        st.caption(
            f"Plan `{plan.plan_id}` | score {plan.score:.4f} | status {plan.status.value} | "
            f"approval required: {plan.approval_required}"
        )
        selected = selected_action_summary(plan)
        if selected is not None:
            st.info(
                f"Selected action: {selected['title']} | {selected['impact']} | {selected['detail']}"
            )
        st.dataframe(plan_actions_dataframe(plan), use_container_width=True)

    if updated_state.pending_plan and updated_state.decision_logs:
        decision_id = updated_state.decision_logs[-1].decision_id
        st.subheader("Pending Approval")
        st.info(f"System is blocked by pending decision `{decision_id}` until it is resolved.")
        st.warning(updated_state.pending_plan.approval_reason or "Manual approval required.")
        approve_col, reject_col, safer_col = st.columns(3)
        if approve_col.button("Approve plan", use_container_width=True):
            updated_state = approve_pending_plan(updated_state, store, decision_id, True)
            st.session_state["app_state"] = updated_state
            st.rerun()
        if reject_col.button("Reject plan", use_container_width=True):
            updated_state = approve_pending_plan(updated_state, store, decision_id, False)
            st.session_state["app_state"] = updated_state
            st.rerun()
        if safer_col.button("Request safer plan", use_container_width=True):
            updated_state = request_safer_plan(updated_state, store, decision_id)
            st.session_state["app_state"] = updated_state
            st.rerun()
    elif not updated_state.decision_logs:
        st.info("No decisions have been generated yet. Run the daily plan or a scenario to start the log.")

    st.subheader("Event Feed")
    feed = event_feed_dataframe(updated_state)
    if feed.empty:
        st.info("No active events. The network is operating in its current planned state.")
    else:
        st.dataframe(feed, use_container_width=True, hide_index=True)

    st.subheader("Inventory")
    st.dataframe(inventory_dataframe(updated_state), use_container_width=True)
    return updated_state
