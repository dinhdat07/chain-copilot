"""Overview page — main dashboard with KPIs, charts, and operational status."""
from __future__ import annotations

import streamlit as st

from core.memory import SQLiteStore
from core.models import SystemState
from orchestrator.service import approve_pending_plan, request_safer_plan, run_daily_plan
from ui.components import (
    render_kpi_cards,
    render_kpi_delta_cards,
    render_mode_banner,
    render_event_pills,
    render_inventory_bar_chart,
    render_supplier_chart,
    render_route_chart,
    render_kpi_comparison_chart,
    render_kpi_radar,
    render_demo_stepper,
    selected_action_summary,
    plan_actions_dataframe,
    inventory_dataframe,
    styled_table,
)
from ui.styles import section_header


def render_page(state: SystemState, store: SQLiteStore) -> SystemState:
    updated = state

    # ── Page header ───────────────────────────────────────────────────────────
    header_left, header_right = st.columns([3, 1])
    with header_left:
        st.markdown(
            '<h1><span class="material-icons">dashboard</span> Network Overview</h1>'
            '<p class="page-subtitle">Real-time supply chain health and control tower status.</p>',
            unsafe_allow_html=True,
        )
    with header_right:
        st.markdown('<div style="height:1.5rem"></div>', unsafe_allow_html=True)
        is_blocked = updated.pending_plan is not None
        if st.button("Run Daily Plan", icon=":material/play_arrow:", type="primary", use_container_width=True, disabled=is_blocked):
            updated = run_daily_plan(state, store)
            st.session_state["app_state"] = updated
            st.rerun()

    # ── Mode banner ───────────────────────────────────────────────────────────
    render_mode_banner(updated)

    # ── Pending approval block ────────────────────────────────────────────────
    if updated.pending_plan and updated.decision_logs:
        decision_id = updated.decision_logs[-1].decision_id
        st.markdown(
            f'<div class="approval-block">'
            f'<div class="approval-title">🔒 Pending Approval — {decision_id}</div>'
            f'<div class="approval-detail">{updated.pending_plan.approval_reason or "Manual approval required before continuing."}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        ac, rc, sc = st.columns(3)
        if ac.button("Approve", icon=":material/check:", use_container_width=True, type="primary"):
            updated = approve_pending_plan(updated, store, decision_id, True)
            st.session_state["app_state"] = updated
            st.rerun()
        if rc.button("Reject", icon=":material/close:", use_container_width=True):
            updated = approve_pending_plan(updated, store, decision_id, False)
            st.session_state["app_state"] = updated
            st.rerun()
        if sc.button("Safer Plan", icon=":material/shield:", use_container_width=True):
            updated = request_safer_plan(updated, store, decision_id)
            st.session_state["app_state"] = updated
            st.rerun()
        st.markdown("---")

    # ── KPI cards ─────────────────────────────────────────────────────────────
    section_header("Key Performance Indicators")
    render_kpi_cards(updated)

    st.markdown("---")

    # ── Two column: Stepper + Events ──────────────────────────────────────────
    left, right = st.columns([3, 2])

    with left:
        section_header(":material/map: Agentic Loop Progress", "Sense → Analyze → Plan → Act → Learn")
        render_demo_stepper(updated)

    with right:
        section_header(":material/sensors: Active Events")
        render_event_pills(updated)

        if not updated.decision_logs:
            st.info("No decisions yet. Click **Run Daily Plan** to begin.")

    st.markdown("---")

    # ── Charts: KPI Before vs After ───────────────────────────────────────────
    if updated.decision_logs:
        latest = updated.decision_logs[-1]
        section_header(":material/trending_up: KPI Impact — Before vs After")

        tab_bar, tab_radar = st.tabs([":material/bar_chart: Bar Chart", ":material/radar: Radar Chart"])
        with tab_bar:
            render_kpi_comparison_chart(latest.before_kpis, latest.after_kpis)
        with tab_radar:
            render_kpi_radar(latest.before_kpis, latest.after_kpis)

        render_kpi_delta_cards(latest.before_kpis, latest.after_kpis)
        st.markdown("---")

    # ── Latest plan ───────────────────────────────────────────────────────────
    if updated.latest_plan:
        plan = updated.latest_plan
        section_header(":material/list_alt: Active Plan",
                       f"{plan.plan_id} · Score {plan.score:.4f} · {plan.status.value}")
        sel = selected_action_summary(plan)
        if sel:
            st.info(f"**{sel['title']}** — {sel['impact']}\n\n{sel['detail']}")
        styled_table(plan_actions_dataframe(plan))
        st.markdown("---")

    # ── Network data visualizations ───────────────────────────────────────────
    section_header(":material/factory: Supply Chain Network")

    net_inv, net_sup, net_route = st.tabs([":material/inventory_2: Inventory", ":material/local_shipping: Suppliers", ":material/route: Routes"])

    with net_inv:
        render_inventory_bar_chart(updated)
        with st.expander("View inventory table"):
            styled_table(inventory_dataframe(updated))

    with net_sup:
        render_supplier_chart(updated)

    with net_route:
        render_route_chart(updated)

    return updated
