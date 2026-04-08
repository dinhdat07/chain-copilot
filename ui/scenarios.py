from __future__ import annotations

import streamlit as st

from core.memory import SQLiteStore
from core.models import SystemState
from simulation.runner import ScenarioRunner
from simulation.scenarios import list_scenarios


def render_page(state: SystemState, store: SQLiteStore) -> SystemState:
    st.title("Scenarios")
    st.write("Run one of the four disruption scenarios against the current digital twin.")
    runner = ScenarioRunner(store=store)
    updated_state = state
    blocked = updated_state.pending_plan is not None
    if blocked and updated_state.decision_logs:
        st.warning(
            "Scenario execution is paused until pending approval is resolved. "
            f"Current decision: {updated_state.decision_logs[-1].decision_id}"
        )
    for name in list_scenarios():
        if st.button(f"Run {name}", use_container_width=True, disabled=blocked):
            updated_state = runner.run(state, name)
            st.success(f"Completed scenario: {name}")
    if updated_state.latest_plan:
        st.subheader("Latest Plan")
        st.json(updated_state.latest_plan.model_dump(mode="json"))
    if updated_state.pending_plan and updated_state.decision_logs:
        st.warning(
            "Scenario generated a pending approval plan. Review it from Overview. "
            f"Decision: {updated_state.decision_logs[-1].decision_id}"
        )
    return updated_state
