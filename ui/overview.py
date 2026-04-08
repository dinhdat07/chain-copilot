from __future__ import annotations

import pandas as pd
import streamlit as st

from core.models import SystemState
from ui.components import inventory_dataframe, render_kpis


def render_page(state: SystemState) -> None:
    st.title("Overview")
    st.caption(f"Mode: {state.mode.value}")
    render_kpis(state)
    st.subheader("Inventory")
    st.dataframe(inventory_dataframe(state), use_container_width=True)
    st.subheader("Active Events")
    active_events = [
        {
            "event_id": event.event_id,
            "type": event.type.value,
            "severity": event.severity,
            "source": event.source,
        }
        for event in state.active_events
    ]
    st.dataframe(pd.DataFrame(active_events), use_container_width=True)
