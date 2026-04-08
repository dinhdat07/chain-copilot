from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.memory import SQLiteStore  # noqa: E402
from core.state import load_initial_state  # noqa: E402
from orchestrator.service import reset_runtime  # noqa: E402
from ui import decision_log, overview, scenarios, what_if  # noqa: E402


def _ensure_state() -> None:
    if "app_state" not in st.session_state:
        st.session_state["app_state"] = load_initial_state()
    if "store" not in st.session_state:
        st.session_state["store"] = SQLiteStore()


def main() -> None:
    st.set_page_config(page_title="ChainCopilot", layout="wide")
    _ensure_state()
    state = st.session_state["app_state"]
    store = st.session_state["store"]

    st.sidebar.title("ChainCopilot")
    page = st.sidebar.radio(
        "Page",
        ["Overview", "Scenarios", "Decision Log", "What-if"],
    )
    if st.sidebar.button("Reset State", use_container_width=True):
        st.session_state["app_state"] = reset_runtime(store)
        state = st.session_state["app_state"]
        st.rerun()

    if page == "Overview":
        st.session_state["app_state"] = overview.render_page(state, store)
    elif page == "Scenarios":
        st.session_state["app_state"] = scenarios.render_page(state, store)
    elif page == "Decision Log":
        decision_log.render_page(state, store)
    else:
        what_if.render_page(state)


if __name__ == "__main__":
    main()
