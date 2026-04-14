"""What-if Simulator — compare current vs simulated KPIs with rich visualizations."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.models import SystemState
from core.state import clone_state
from orchestrator.graph import build_graph
from simulation.scenarios import get_scenario_events, list_scenarios
from ui.components import (
    render_kpi_cards,
    render_kpi_delta_cards,
    render_kpi_comparison_chart,
    render_kpi_radar,
    selected_action_summary,
    plan_actions_dataframe,
    styled_table,
)
from ui.styles import section_header


def _cost_comparison_chart(before_cost: float, after_cost: float) -> None:
    """Simple bar chart comparing total cost."""
    chart = pd.DataFrame(
        {"Total Cost": [before_cost, after_cost]},
        index=["Current", "Simulated"],
    )
    st.bar_chart(chart)


def render_page(state: SystemState) -> None:
    st.markdown(
        '<h1><span class="material-icons">auto_awesome</span> What-if Simulator</h1>'
        '<p class="page-subtitle">Explore how a disruption scenario would impact your network — without committing any changes.</p>',
        unsafe_allow_html=True,
    )

    # ── Controls ──────────────────────────────────────────────────────────────
    col_sel, col_btn = st.columns([3, 1])
    with col_sel:
        scenario_name = st.selectbox("Choose scenario", list_scenarios(), index=0)
    with col_btn:
        st.markdown('<div style="height:1.65rem"></div>', unsafe_allow_html=True)
        run_sim = st.button("Simulate", icon=":material/science:", type="primary", use_container_width=True)

    st.markdown("---")

    # ── Current KPIs ──────────────────────────────────────────────────────────
    section_header(":material/monitoring: Current Network KPIs")
    render_kpi_cards(state)

    # ── Simulation ────────────────────────────────────────────────────────────
    if run_sim:
        with st.spinner(f"Simulating **{scenario_name}**…"):
            graph = build_graph()
            simulated = clone_state(state)
            for event in get_scenario_events(scenario_name):
                simulated = graph.invoke(simulated, event)

        st.markdown("---")
        section_header(f":material/science: Simulation Result — {scenario_name}",
                       "Compare current state against simulated outcome")

        # KPI delta cards
        render_kpi_delta_cards(state.kpis, simulated.kpis)

        st.markdown("<br>", unsafe_allow_html=True)

        # Charts in tabs
        tab_bar, tab_radar, tab_cost = st.tabs([":material/bar_chart: Bar Comparison", ":material/radar: Radar Overlay", ":material/attach_money: Cost Impact"])

        with tab_bar:
            render_kpi_comparison_chart(state.kpis, simulated.kpis)

        with tab_radar:
            render_kpi_radar(state.kpis, simulated.kpis)

        with tab_cost:
            _cost_comparison_chart(state.kpis.total_cost, simulated.kpis.total_cost)

        # Simulated plan
        if simulated.latest_plan:
            st.markdown("---")
            plan = simulated.latest_plan
            section_header(":material/list_alt: Simulated Plan",
                           f"{plan.plan_id} · Mode: {plan.mode.value} · Score: {plan.score:.4f}")
            sel = selected_action_summary(plan)
            if sel:
                st.info(f"**{sel['title']}** — {sel['impact']}\n\n{sel['detail']}")
            styled_table(plan_actions_dataframe(plan))

        st.success("✅ Simulation complete. No changes were made to the live system.")
