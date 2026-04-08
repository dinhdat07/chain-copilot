from __future__ import annotations

import streamlit as st

from core.models import SystemState
from core.state import clone_state
from orchestrator.graph import build_graph
from simulation.scenarios import list_scenarios, get_scenario_events
from ui.components import (
    kpi_delta_dataframe,
    plan_actions_dataframe,
    render_kpis,
    selected_action_summary,
)


def render_page(state: SystemState) -> None:
    st.title("What-if Simulator")
    scenario_name = st.selectbox("Scenario", list_scenarios(), index=0)
    st.subheader("Current Network KPIs")
    render_kpis(state)
    if st.button("Simulate alternative plan", width="stretch"):
        graph = build_graph()
        simulated = clone_state(state)
        for event in get_scenario_events(scenario_name):
            simulated = graph.invoke(simulated, event)
        if simulated.latest_plan:
            st.subheader("Simulated Plan")
            st.caption(
                f"Plan `{simulated.latest_plan.plan_id}` | mode {simulated.latest_plan.mode.value} | "
                f"score {simulated.latest_plan.score:.4f} | approval required: "
                f"{simulated.latest_plan.approval_required}"
            )
            selected = selected_action_summary(simulated.latest_plan)
            if selected is not None:
                st.info(
                    f"Selected action: {selected['title']} | {selected['impact']} | {selected['detail']}"
                )
            st.dataframe(
                plan_actions_dataframe(simulated.latest_plan),
                width="stretch",
                hide_index=True,
            )
        st.subheader("Current vs Simulated KPIs")
        st.dataframe(
            kpi_delta_dataframe(state.kpis, simulated.kpis),
            width="stretch",
            hide_index=True,
        )
