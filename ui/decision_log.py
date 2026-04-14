"""Decision Log page — timeline, score breakdown donut, learned memory tabs."""
from __future__ import annotations

import streamlit as st

from core.enums import ApprovalStatus
from core.memory import SQLiteStore
from core.models import DecisionLog, SystemState
from ui.components import (
    approval_badge,
    memory_tables,
    rejected_actions_dataframe,
    render_score_breakdown,
    render_kpi_comparison_chart,
    styled_table,
)
from ui.styles import section_header


def _render_decision_details(log: DecisionLog) -> None:
    """Full explainability view for a single decision."""
    st.markdown(f"**Rationale:** {log.rationale}")

    col_a, col_b = st.columns(2)
    with col_a:
        section_header(":material/pie_chart: Score Breakdown")
        render_score_breakdown(log)
    with col_b:
        section_header(":material/trending_up: KPI Before → After")
        render_kpi_comparison_chart(log.before_kpis, log.after_kpis)

    if log.winning_factors:
        section_header(":material/emoji_events: Winning Factors")
        for f in log.winning_factors:
            st.markdown(f"- {f}")

    if log.rejected_actions:
        section_header(":material/block: Rejected Alternatives")
        rj = rejected_actions_dataframe(log)
        if not rj.empty:
            styled_table(rj)


@st.dialog("Decision Details", width="large")
def _show_dialog(log: DecisionLog) -> None:
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">'
        f'<code>{log.decision_id}</code> {approval_badge(log)}</div>',
        unsafe_allow_html=True,
    )
    _render_decision_details(log)


def _timeline_html(logs: list[DecisionLog]) -> str:
    """Generate vertical timeline HTML."""
    dot_colors = {
        ApprovalStatus.APPROVED: "#059669",
        ApprovalStatus.AUTO_APPLIED: "#4F46E5",
        ApprovalStatus.PENDING: "#D97706",
        ApprovalStatus.REJECTED: "#E11D48",
        ApprovalStatus.NOT_REQUIRED: "#94A3B8",
    }
    html = ""
    for i, log in enumerate(logs):
        color = dot_colors.get(log.approval_status, "#94A3B8")
        line = '<div class="timeline-line"></div>' if i < len(logs) - 1 else ""
        status_badge = approval_badge(log)

        html += (
            f'<div class="timeline-item">'
            f'<div class="timeline-rail">'
            f'<div class="timeline-dot" style="background:{color};"></div>'
            f'{line}</div>'
            f'<div class="timeline-card">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<span class="timeline-id">{log.decision_id}</span>'
            f'{status_badge}</div>'
            f'<div class="timeline-meta">'
            f'Plan: {log.plan_id} · Service: {log.after_kpis.service_level:.1%} · Cost: ${log.after_kpis.total_cost:,.0f}'
            f'</div></div></div>'
        )
    return html


def render_page(state: SystemState, store: SQLiteStore) -> None:
    st.markdown(
        '<h1><span class="material-icons">list_alt</span> Decision Log</h1>'
        '<p class="page-subtitle">Full audit trail of AI decisions with explainability and learned memory.</p>',
        unsafe_allow_html=True,
    )

    # ── Latest decision ───────────────────────────────────────────────────────
    if state.decision_logs:
        latest = state.decision_logs[-1]
        section_header(
            ":material/psychology: Latest Decision",
            f"{latest.decision_id} · Plan {latest.plan_id}",
        )
        st.markdown(approval_badge(latest), unsafe_allow_html=True)

        if state.pending_plan:
            st.warning("⏳ A plan is **pending approval**. Resolve it in Overview before generating new plans.")

        _render_decision_details(latest)
    else:
        st.info("No decisions yet. Run the daily plan or a scenario to generate the first decision.")

    st.markdown("---")

    # ── Session timeline ──────────────────────────────────────────────────────
    section_header(":material/history: Session Timeline", "All decisions from this session in chronological order")
    if state.decision_logs:
        st.markdown(_timeline_html(list(reversed(state.decision_logs))), unsafe_allow_html=True)
    else:
        st.info("Timeline will appear after the first plan is generated.")

    st.markdown("---")

    # ── Persisted logs ────────────────────────────────────────────────────────
    section_header(":material/save: Persisted Logs", "All decisions saved to persistent storage (SQLite)")
    items = store.list_decision_logs()
    if items:
        persisted = [DecisionLog.model_validate(item) for item in items]
        for log in persisted:
            with st.container(border=True):
                cc1, cc2, cc3, cc4 = st.columns([3, 2, 2, 1])
                cc1.markdown(f"`{log.decision_id}`")
                cc2.caption(log.plan_id)
                cc3.markdown(approval_badge(log), unsafe_allow_html=True)
                if cc4.button("Details", key=f"dlg_{log.decision_id}", use_container_width=True):
                    _show_dialog(log)
    else:
        st.info("No persisted decision logs yet.")

    st.markdown("---")

    # ── Learned memory ────────────────────────────────────────────────────────
    section_header(":material/memory: Learned Memory", "Accumulated knowledge from past operations")
    sup_df, route_df, scen_df = memory_tables(state)

    tab_sup, tab_route, tab_scen = st.tabs([":material/factory: Supplier Reliability", ":material/route: Route Priors", ":material/folder: Scenario History"])

    with tab_sup:
        if sup_df.empty:
            st.info("No supplier learning data yet.")
        else:
            styled_table(sup_df)

    with tab_route:
        if route_df.empty:
            st.info("No route learning data yet.")
        else:
            styled_table(route_df)

    with tab_scen:
        if scen_df.empty:
            st.info("No scenario history recorded yet.")
        else:
            styled_table(scen_df)
