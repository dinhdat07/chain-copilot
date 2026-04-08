from __future__ import annotations

import streamlit as st

from core.models import SystemState
from core.state import clone_state
from orchestrator.graph import build_graph
from simulation.scenarios import list_scenarios, get_scenario_events


def render_page(state: SystemState) -> None:
    st.title("What-if Simulator")
    scenario_name = st.selectbox("Scenario", list_scenarios(), index=0)
    if st.button("Simulate alternative plan", use_container_width=True):
        graph = build_graph()
        simulated = clone_state(state)
        for event in get_scenario_events(scenario_name):
            simulated = graph.invoke(simulated, event)
        if simulated.latest_plan:
            st.subheader("Simulated Plan")
            st.json(simulated.latest_plan.model_dump(mode="json"))
        st.subheader("Simulated KPIs")
        st.json(simulated.kpis.model_dump(mode="json"))
