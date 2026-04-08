from __future__ import annotations

import pandas as pd
import streamlit as st

from core.memory import SQLiteStore
from core.models import SystemState
from ui.components import decision_log_dataframe


def render_page(state: SystemState, store: SQLiteStore) -> None:
    st.title("Decision Log")
    st.subheader("Current Session")
    st.dataframe(decision_log_dataframe(state), use_container_width=True)
    st.subheader("Persisted Logs")
    items = store.list_decision_logs()
    st.dataframe(pd.DataFrame(items), use_container_width=True)
