"""Scenarios page — trigger disruption scenarios with visual card grid and KPI impact charts."""
from __future__ import annotations

import streamlit as st

from core.memory import SQLiteStore
from core.models import SystemState
from simulation.runner import ScenarioRunner
from simulation.scenarios import list_scenarios
from ui.components import (
    render_kpi_comparison_chart,
    render_kpi_delta_cards,
    render_kpi_radar,
    selected_action_summary,
    plan_actions_dataframe,
    styled_table,
)
from ui.styles import section_header


SCENARIO_META = {
    "supplier_delay":       ("local_shipping", "Supplier Delay",       "Primary supplier reliability drops. Replenishment slows significantly."),
    "demand_spike":         ("trending_up", "Demand Spike",         "Demand jumps suddenly. Stockout pressure rises on critical SKUs."),
    "route_blockage":       ("route", "Route Blockage",       "A route disruption forces cost vs. speed trade-offs in logistics."),
    "compound_disruption":  ("warning", "Compound Disruption",  "Multiple disruptions combine into a high-risk recovery challenge."),
}


def render_page(state: SystemState, store: SQLiteStore) -> SystemState:
    updated = state
    runner = ScenarioRunner(store=store)
    blocked = updated.pending_plan is not None

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(
        '<h1><span class="material-icons">science</span> Disruption Scenarios</h1>'
        '<p class="page-subtitle">Trigger a scenario to test crisis detection, autonomous replanning, and the approval flow.</p>',
        unsafe_allow_html=True,
    )

    if blocked and updated.decision_logs:
        st.warning(
            f"⏳ Scenario execution paused — resolve pending approval "
            f"`{updated.decision_logs[-1].decision_id}` in **Overview** first."
        )

    st.caption("💡 Recommended: run the daily plan first, then trigger **Supplier Delay**.")
    st.markdown("---")

    # ── Scenario card grid (2 × 2) ───────────────────────────────────────────
    names = list_scenarios()
    pairs = [names[i:i+2] for i in range(0, len(names), 2)]

    for pair in pairs:
        cols = st.columns(2, gap="medium")
        for col, name in zip(cols, pair):
            icon, title, desc = SCENARIO_META.get(name, ("build", name, ""))
            disabled_cls = " blocked" if blocked else ""

            with col:
                st.markdown(
                    f'<div class="scenario-card{disabled_cls}">'
                    f'<div class="scenario-icon"><span class="material-icons">{icon}</span></div>'
                    f'<div class="scenario-title">{title}</div>'
                    f'<div class="scenario-desc">{desc}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if st.button(f"{title}", icon=":material/play_arrow:", key=f"run_{name}", use_container_width=True,
                             disabled=blocked, type="primary"):
                    updated = runner.run(updated, name)
                    st.session_state["app_state"] = updated
                    st.success(f"**{title}** scenario completed.", icon=":material/check_circle:")
                    st.rerun()

    # ── Results ───────────────────────────────────────────────────────────────
    if updated.latest_plan:
        st.markdown("---")
        plan = updated.latest_plan
        section_header(":material/list_alt: Latest Plan",
                       f"{plan.plan_id} · Mode: {plan.mode.value} · Score: {plan.score:.4f}")

        sel = selected_action_summary(plan)
        if sel:
            st.info(f"**{sel['title']}** — {sel['impact']}\n\n{sel['detail']}")
        styled_table(plan_actions_dataframe(plan))

    if updated.decision_logs:
        st.markdown("---")
        latest = updated.decision_logs[-1]
        section_header(":material/trending_up: KPI Impact", "How this scenario changed your network performance")

        tab_bar, tab_radar = st.tabs([":material/bar_chart: Bar Comparison", ":material/radar: Radar Overlay"])
        with tab_bar:
            render_kpi_comparison_chart(latest.before_kpis, latest.after_kpis)
        with tab_radar:
            render_kpi_radar(latest.before_kpis, latest.after_kpis)

        render_kpi_delta_cards(latest.before_kpis, latest.after_kpis)

    if updated.pending_plan and updated.decision_logs:
        st.markdown("---")
        st.warning(
            f"⚠️ This scenario generated a **pending approval** plan. "
            f"Go to **Overview** to approve or reject decision `{updated.decision_logs[-1].decision_id}`."
        )

    return updated
