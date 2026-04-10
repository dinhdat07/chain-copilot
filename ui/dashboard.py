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
from ui.styles import inject_css  # noqa: E402


def _ensure_state() -> None:
    if "app_state" not in st.session_state:
        st.session_state["app_state"] = load_initial_state()
    if "store" not in st.session_state:
        st.session_state["store"] = SQLiteStore()


PAGES = {
    "Overview":        ":material/dashboard:",
    "Scenarios":       ":material/science:",
    "Decision Log":    ":material/list_alt:",
    "What-if":         ":material/auto_awesome:",
}


def main() -> None:
    st.set_page_config(
        page_title="ChainCopilot — Supply Chain Control Tower",
        page_icon=":material/link:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()
    _ensure_state()

    state = st.session_state["app_state"]
    store = st.session_state["store"]

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown(
            '<p style="font-size:1.15rem;font-weight:800;color:#1E293B;margin-bottom:0;">:material/link: ChainCopilot</p>'
            '<p style="font-size:0.72rem;color:#64748B;margin-top:2px;">Supply Chain Control Tower</p>',
            unsafe_allow_html=True,
        )
        st.markdown("---")

        # Navigation
        selected = None
        for pg, icon in PAGES.items():
            if st.button(f"{pg}", icon=icon, key=f"nav_{pg}", use_container_width=True):
                st.session_state["current_page"] = pg

        if "current_page" not in st.session_state:
            st.session_state["current_page"] = "Overview"

        st.markdown("---")

        if st.button("Reset System", icon=":material/refresh:", use_container_width=True):
            st.session_state["app_state"] = reset_runtime(store)
            st.rerun()

        st.markdown(
            '<p style="font-size:0.65rem;color:#94A3B8;margin-top:2rem;">v0.1.0 — Hackathon MVP</p>',
            unsafe_allow_html=True,
        )

    # ── Page dispatch ─────────────────────────────────────────────────────────
    page = st.session_state["current_page"]

    if page == "Overview":
        st.session_state["app_state"] = overview.render_page(state, store)
    elif page == "Scenarios":
        st.session_state["app_state"] = scenarios.render_page(state, store)
    elif page == "Decision Log":
        decision_log.render_page(state, store)
    elif page == "What-if":
        what_if.render_page(state)


if __name__ == "__main__":
    main()
