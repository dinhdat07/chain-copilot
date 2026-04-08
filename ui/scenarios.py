from __future__ import annotations

import streamlit as st

from core.memory import SQLiteStore
from core.models import SystemState
from simulation.runner import ScenarioRunner
from simulation.scenarios import list_scenarios


SCENARIO_DESCRIPTIONS = {
    "supplier_delay": "Primary supplier reliability drops and replenishment slows down.",
    "demand_spike": "Demand jumps suddenly and stockout pressure rises on a critical SKU.",
    "route_blockage": "A route disruption forces a cost versus speed trade-off in logistics.",
    "compound_disruption": "Supplier and route disruption combine into a high-risk recovery case.",
}


def render_page(state: SystemState, store: SQLiteStore) -> SystemState:
    st.title("Scenarios")
    st.write("Trigger a disruption to show crisis detection, replanning, and approval flow.")
    st.caption("Recommended demo path: run the daily plan first, then trigger `supplier_delay`.")
    runner = ScenarioRunner(store=store)
    updated_state = state
    blocked = updated_state.pending_plan is not None
    if blocked and updated_state.decision_logs:
        st.warning(
            "Scenario execution is paused until pending approval is resolved. "
            f"Current decision: {updated_state.decision_logs[-1].decision_id}"
        )
    for name in list_scenarios():
        st.write(f"`{name}`: {SCENARIO_DESCRIPTIONS.get(name, 'Disruption scenario')}")
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
