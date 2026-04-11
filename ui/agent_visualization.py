from __future__ import annotations

import streamlit as st

from core.models import SystemState
from ui.components import (
    agent_node_payload,
    candidate_plan_dataframe,
    candidate_score_breakdown_dataframe,
    latest_reflection_snapshot,
    pipeline_graph_source,
    pipeline_node_labels,
    pipeline_node_status_map,
    reflection_timeline_dataframe,
)


def _render_reasoning_panel(state: SystemState) -> None:
    labels = pipeline_node_labels()
    options = list(labels)
    default_index = options.index("planner") if "planner" in options else 0
    selected_node = st.selectbox(
        "Select a node to inspect",
        options,
        index=default_index,
        format_func=lambda key: labels[key],
    )
    payload = agent_node_payload(state, selected_node)

    st.subheader(payload["title"])
    st.caption(payload["reasoning_source"])
    st.dataframe(payload["input_summary"], width="stretch", hide_index=True)
    st.write(payload["summary"])

    if payload["key_factors"]:
        st.write("Key factors")
        for item in payload["key_factors"]:
            st.write(f"- {item}")

    if payload["recommended_actions"]:
        st.write("Recommended / selected actions")
        for item in payload["recommended_actions"]:
            st.write(f"- {item}")

    if payload["tradeoffs"]:
        st.write("Tradeoffs / concerns")
        for item in payload["tradeoffs"]:
            st.write(f"- {item}")

    if payload["llm_used"]:
        st.success("AI reasoning was used for this node.")
    elif payload["llm_error"]:
        st.warning(f"AI unavailable. Fallback used. Error: {payload['llm_error']}")
    else:
        st.info("Deterministic or fallback reasoning is currently driving this node.")


def _render_candidate_plans(state: SystemState) -> None:
    latest_decision = state.decision_logs[-1] if state.decision_logs else None
    frame = candidate_plan_dataframe(state)
    st.subheader("Planner Candidate Plans")
    if frame.empty or latest_decision is None:
        st.info("No candidate plans are available until the planner has executed.")
        return

    st.dataframe(frame, width="stretch", hide_index=True)
    evaluations = {
        evaluation.strategy_label: evaluation
        for evaluation in latest_decision.candidate_evaluations
    }
    ordered = ["cost_first", "balanced", "resilience_first"]
    cols = st.columns(3)
    for col, strategy_label in zip(cols, ordered):
        evaluation = evaluations.get(strategy_label)
        if evaluation is None:
            continue
        with col:
            is_selected = state.latest_plan is not None and state.latest_plan.strategy_label == strategy_label
            if is_selected:
                st.success(f"Selected: {strategy_label}")
            else:
                st.info(f"Alternative: {strategy_label}")
            st.metric("Score", f"{evaluation.score:.4f}")
            st.metric("Service", f"{evaluation.projected_kpis.service_level:.1%}")
            st.metric("Risk", f"{evaluation.projected_kpis.disruption_risk:.1%}")
            st.metric("Recovery", f"{evaluation.projected_kpis.recovery_speed:.1%}")
            st.caption(
                f"Cost {evaluation.projected_kpis.total_cost:,.0f} | "
                f"Approval required: {evaluation.approval_required}"
            )
            st.write(evaluation.rationale)
            st.dataframe(
                candidate_score_breakdown_dataframe(evaluation),
                width="stretch",
                hide_index=True,
            )

    if latest_decision.selection_reason:
        st.write("Why the final plan won")
        st.success(latest_decision.selection_reason)


def _render_critic_and_reflection(state: SystemState) -> None:
    latest_decision = state.decision_logs[-1] if state.decision_logs else None
    critic_col, reflection_col = st.columns(2)

    with critic_col:
        st.subheader("Critic Review")
        if latest_decision is None:
            st.info("Critic output appears after planning has executed.")
        elif latest_decision.critic_summary:
            st.write(latest_decision.critic_summary)
            if latest_decision.critic_findings:
                st.write("Blind spots / cautions")
                for item in latest_decision.critic_findings:
                    st.write(f"- {item}")
        elif latest_decision.critic_error:
            st.warning(f"Critic unavailable. Error: {latest_decision.critic_error}")
        else:
            st.info("No critic feedback recorded for the latest decision.")

    with reflection_col:
        st.subheader("Reflection / Learning")
        latest_reflection = latest_reflection_snapshot(state)
        if latest_reflection is None:
            latest_run = state.scenario_history[-1] if state.scenario_history else None
            if latest_run is not None:
                st.info(f"Reflection status: {latest_run.reflection_status}")
            else:
                st.info("No reflection memory recorded yet.")
        else:
            st.write(latest_reflection["summary"])
            if latest_reflection["lessons"]:
                st.write("Lessons")
                for item in latest_reflection["lessons"]:
                    st.write(f"- {item}")
            if latest_reflection["pattern_tags"]:
                st.write("Pattern tags")
                st.write(", ".join(latest_reflection["pattern_tags"]))
            if latest_reflection["follow_up_checks"]:
                st.write("Follow-up checks")
                for item in latest_reflection["follow_up_checks"]:
                    st.write(f"- {item}")
            if latest_reflection["llm_error"]:
                st.caption(f"Fallback reflection used. Error: {latest_reflection['llm_error']}")

    st.subheader("Reflection History")
    history = reflection_timeline_dataframe(state)
    if history.empty:
        st.info("No finalized reflection history yet.")
    else:
        st.dataframe(history, width="stretch", hide_index=True)


def render_page(state: SystemState) -> None:
    st.title("AI Agents")
    st.write(
        "This view makes the multi-agent workflow visible: specialist interpretation, "
        "candidate-plan generation, deterministic policy selection, approval gating, execution, and learning."
    )

    graph_col, detail_col = st.columns([1.4, 1.0])
    with graph_col:
        st.subheader("Agent Pipeline")
        st.graphviz_chart(pipeline_graph_source(state))
        status_rows = pipeline_node_status_map(state)
        status_frame = [
            {
                "node": status["label"],
                "active": status["active"],
                "tone": status["tone"],
                "detail": status["detail"],
            }
            for status in status_rows.values()
        ]
        st.dataframe(status_frame, width="stretch", hide_index=True)
    with detail_col:
        _render_reasoning_panel(state)

    _render_candidate_plans(state)
    _render_critic_and_reflection(state)
