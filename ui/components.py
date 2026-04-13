from __future__ import annotations

import pandas as pd
import streamlit as st

from core.enums import ActionType, ApprovalStatus, Mode
from core.models import CandidatePlanEvaluation, DecisionLog, KPIState, Plan, SystemState
from ui.styles import badge


def _titleize(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _format_percent(value: float) -> str:
    return f"{value:.1%}"


def _format_delta(metric: str, delta: float) -> str:
    if metric == "total_cost":
        return f"{delta:+,.0f}"
    if metric == "decision_latency_ms":
        return f"{delta:+.0f} ms"
    return f"{delta:+.1%}"


def styled_table(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.info("No data available.")
        return
    st.dataframe(frame, use_container_width=True, hide_index=True)


def render_kpis(state: SystemState) -> None:
    render_kpi_cards(state)


def render_kpi_cards(state: SystemState) -> None:
    metrics = [
        ("Service Level", _format_percent(state.kpis.service_level)),
        ("Total Cost", f"{state.kpis.total_cost:,.0f}"),
        ("Disruption Risk", _format_percent(state.kpis.disruption_risk)),
        ("Recovery Speed", _format_percent(state.kpis.recovery_speed)),
        ("Stockout Risk", _format_percent(state.kpis.stockout_risk)),
    ]
    cols = st.columns(len(metrics))
    for col, (label, value) in zip(cols, metrics):
        col.metric(label, value)


def render_kpi_delta_cards(before: KPIState, after: KPIState) -> None:
    metrics = [
        ("service_level", "Service Level", before.service_level, after.service_level),
        ("total_cost", "Total Cost", before.total_cost, after.total_cost),
        ("disruption_risk", "Disruption Risk", before.disruption_risk, after.disruption_risk),
        ("recovery_speed", "Recovery Speed", before.recovery_speed, after.recovery_speed),
    ]
    cols = st.columns(len(metrics))
    for col, (key, label, old, new) in zip(cols, metrics):
        value = f"{new:,.0f}" if key == "total_cost" else _format_percent(new)
        col.metric(label, value, _format_delta(key, new - old))


def inventory_dataframe(state: SystemState) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "SKU": item.sku,
                "Product": item.name,
                "On Hand": item.on_hand,
                "Incoming": item.incoming_qty,
                "Forecast": item.forecast_qty,
                "Reorder Point": item.reorder_point,
                "Safety Stock": item.safety_stock,
                "Warehouse": item.warehouse_id,
                "Preferred Supplier": item.preferred_supplier_id,
                "Preferred Route": item.preferred_route_id,
            }
            for item in state.inventory.values()
        ]
    )


def plan_actions_dataframe(plan: Plan) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Action": _titleize(action.action_type.value),
                "Target": action.target_id,
                "Reason": action.reason,
                "Cost Delta": action.estimated_cost_delta,
                "Service Delta": action.estimated_service_delta,
                "Risk Delta": action.estimated_risk_delta,
                "Recovery Hours": action.estimated_recovery_hours,
            }
            for action in plan.actions
        ]
    )


def decision_log_dataframe(state: SystemState) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Decision": log.decision_id,
                "Plan": log.plan_id,
                "Approval": _titleize(log.approval_status.value),
                "Service Level": log.after_kpis.service_level,
                "Total Cost": log.after_kpis.total_cost,
                "Rationale": log.rationale,
            }
            for log in reversed(state.decision_logs)
        ]
    )


def rejected_actions_dataframe(log: DecisionLog) -> pd.DataFrame:
    return pd.DataFrame(log.rejected_actions)


def mode_summary(state: SystemState) -> dict[str, str]:
    mapping = {
        Mode.NORMAL: {"label": "Normal Mode", "tone": "success"},
        Mode.CRISIS: {"label": "Crisis Mode", "tone": "warning"},
        Mode.APPROVAL: {"label": "Approval Mode", "tone": "warning"},
    }
    return mapping.get(state.mode, {"label": _titleize(str(state.mode)), "tone": "neutral"})


def render_mode_banner(state: SystemState) -> None:
    summary = mode_summary(state)
    message = summary["label"]
    if state.pending_plan:
        st.warning(f"{message}: approval is required before execution can continue.")
        return
    if state.mode == Mode.CRISIS:
        st.warning(f"{message}: the control tower is prioritizing resilience and recovery.")
        return
    st.success(f"{message}: the network is operating within normal thresholds.")


def approval_badge(log: DecisionLog) -> str:
    variant_map = {
        ApprovalStatus.APPROVED: "green",
        ApprovalStatus.AUTO_APPLIED: "blue",
        ApprovalStatus.PENDING: "yellow",
        ApprovalStatus.REJECTED: "red",
        ApprovalStatus.NOT_REQUIRED: "gray",
    }
    variant = variant_map.get(log.approval_status, "gray")
    return badge(_titleize(log.approval_status.value), variant)


def render_event_pills(state: SystemState) -> None:
    if not state.active_events:
        st.info("No active disruptions.")
        return
    pills = []
    for event in state.active_events:
        pills.append(
            badge(
                f"{_titleize(event.type.value)} · severity {event.severity:.2f}",
                "yellow" if event.severity < 0.8 else "red",
            )
        )
    st.markdown(" ".join(pills), unsafe_allow_html=True)


def kpi_delta_dataframe(before: KPIState, after: KPIState) -> pd.DataFrame:
    metrics = [
        ("service_level", before.service_level, after.service_level),
        ("total_cost", before.total_cost, after.total_cost),
        ("disruption_risk", before.disruption_risk, after.disruption_risk),
        ("recovery_speed", before.recovery_speed, after.recovery_speed),
        ("stockout_risk", before.stockout_risk, after.stockout_risk),
    ]
    return pd.DataFrame(
        [
            {"metric": name, "before": old, "after": new, "delta": new - old}
            for name, old, new in metrics
        ]
    )


def render_kpi_comparison_chart(before: KPIState, after: KPIState) -> None:
    chart = pd.DataFrame(
        [
            {"metric": "Service Level", "before": before.service_level, "after": after.service_level},
            {"metric": "Disruption Risk", "before": before.disruption_risk, "after": after.disruption_risk},
            {"metric": "Recovery Speed", "before": before.recovery_speed, "after": after.recovery_speed},
            {"metric": "Stockout Risk", "before": before.stockout_risk, "after": after.stockout_risk},
        ]
    ).set_index("metric")
    st.bar_chart(chart)


def render_kpi_radar(before: KPIState, after: KPIState) -> None:
    chart = pd.DataFrame(
        {
            "Current": [
                before.service_level,
                1 - before.disruption_risk,
                before.recovery_speed,
                1 - before.stockout_risk,
            ],
            "Simulated": [
                after.service_level,
                1 - after.disruption_risk,
                after.recovery_speed,
                1 - after.stockout_risk,
            ],
        },
        index=["Service", "Stability", "Recovery", "Availability"],
    )
    st.line_chart(chart)


def render_inventory_bar_chart(state: SystemState) -> None:
    frame = inventory_dataframe(state)
    if frame.empty:
        st.info("No inventory records available.")
        return
    chart = frame.set_index("SKU")[["On Hand", "Incoming", "Forecast"]]
    st.bar_chart(chart)


def render_supplier_chart(state: SystemState) -> None:
    frame = pd.DataFrame(
        [
            {
                "Supplier": record.supplier_id,
                "SKU": record.sku,
                "Reliability": record.reliability,
                "Lead Time (days)": record.lead_time_days,
                "Unit Cost": record.unit_cost,
                "Status": record.status,
            }
            for record in state.suppliers.values()
        ]
    )
    styled_table(frame)


def render_route_chart(state: SystemState) -> None:
    frame = pd.DataFrame(
        [
            {
                "Route": record.route_id,
                "Origin": record.origin,
                "Destination": record.destination,
                "Transit Days": record.transit_days,
                "Cost": record.cost,
                "Risk": record.risk_score,
                "Status": record.status,
            }
            for record in state.routes.values()
        ]
    )
    styled_table(frame)


def selected_action_summary(plan: Plan | None) -> dict[str, str] | None:
    if plan is None or not plan.actions:
        return None
    selected = next(
        (action for action in plan.actions if action.action_type != ActionType.NO_OP),
        plan.actions[0],
    )
    detail = selected.reason or "No additional reasoning recorded."
    return {
        "title": f"{_titleize(selected.action_type.value)} {selected.target_id}",
        "impact": (
            f"Service {selected.estimated_service_delta:+.0%}, "
            f"Cost {selected.estimated_cost_delta:+.0f}, "
            f"Risk {selected.estimated_risk_delta:+.0%}"
        ),
        "detail": detail,
        "reason": detail,
    }


def demo_flow_dataframe(state: SystemState) -> pd.DataFrame:
    trace = state.latest_trace
    approval_status = (
        state.decision_logs[-1].approval_status.value
        if state.decision_logs
        else ApprovalStatus.NOT_REQUIRED.value
    )
    rows = [
        {"step": "1. Daily plan", "status": "complete"},
        {
            "step": "2. Disruption detected",
            "status": "complete" if state.active_events else "not started",
        },
        {
            "step": "3. Autonomous replan",
            "status": "complete" if state.latest_plan else "not started",
        },
        {
            "step": "4. Approval workflow",
            "status": (
                "waiting for approval"
                if approval_status == ApprovalStatus.PENDING.value
                else "complete"
            ),
        },
        {
            "step": "5. Learn from outcomes",
            "status": "complete" if state.scenario_history else "not started",
        },
    ]
    if trace is not None and trace.execution_status == "rejected":
        rows[-1]["status"] = "paused"
    return pd.DataFrame(rows)


def render_demo_stepper(state: SystemState) -> None:
    flow = demo_flow_dataframe(state).to_dict(orient="records")
    cols = st.columns(len(flow))
    for col, row in zip(cols, flow):
        status = row["status"]
        if status == "complete":
            col.success(row["step"])
        elif "waiting" in status:
            col.warning(f"{row['step']}\n{status}")
        else:
            col.info(f"{row['step']}\n{status}")


def pipeline_graph_source(state: SystemState) -> str:
    trace = state.latest_trace
    terminal = trace.terminal_stage if trace else "execution"
    final_edge = "decision_engine -> execution"
    if terminal == "approval":
        final_edge = "decision_engine -> approval_gate"
    return "\n".join(
        [
            "risk_agent -> demand_agent",
            "demand_agent -> inventory_agent",
            "inventory_agent -> supplier_agent",
            "supplier_agent -> logistics_agent",
            "logistics_agent -> planner_agent",
            "planner_agent -> critic_agent",
            "critic_agent -> decision_engine",
            final_edge,
            "approval_gate -> reflection_memory",
            "execution -> reflection_memory",
            "Risk Agent",
            "Planner Agent",
            "Approval Gate",
            "Reflection / Memory",
        ]
    )


def pipeline_node_labels() -> dict[str, str]:
    return {
        "risk": "Risk Agent",
        "demand": "Demand Agent",
        "inventory": "Inventory Agent",
        "supplier": "Supplier Agent",
        "logistics": "Logistics Agent",
        "planner": "Planner Agent",
        "critic": "Critic Agent",
    }


def pipeline_node_status_map(state: SystemState) -> dict[str, dict[str, object]]:
    labels = {
        "risk_agent": "Risk Agent",
        "demand_agent": "Demand Agent",
        "inventory_agent": "Inventory Agent",
        "supplier_agent": "Supplier Agent",
        "logistics_agent": "Logistics Agent",
        "planner_agent": "Planner Agent",
        "critic_agent": "Critic Agent",
        "decision_engine": "Decision Engine",
        "approval_gate": "Approval Gate",
        "execution": "Execution",
        "reflection_memory": "Reflection / Memory",
    }
    statuses: dict[str, dict[str, object]] = {
        key: {"label": label, "active": False, "tone": "normal", "detail": "Idle", "status": "idle"}
        for key, label in labels.items()
    }
    trace = state.latest_trace
    if trace is None:
        return statuses

    for step in trace.steps:
        key = f"{step.node_key}_agent"
        if key in statuses:
            statuses[key] = {
                "label": labels[key],
                "active": step.status == "running",
                "tone": "complete" if step.status == "completed" else "normal",
                "detail": step.summary or step.status.title(),
                "status": step.status,
            }

    statuses["decision_engine"] = {
        "label": labels["decision_engine"],
        "active": False,
        "tone": "complete",
        "detail": trace.selection_reason or "Policy scoring complete.",
        "status": "completed",
    }
    if trace.terminal_stage == "approval":
        statuses["approval_gate"] = {
            "label": labels["approval_gate"],
            "active": True,
            "tone": "approval",
            "detail": trace.approval_reason or "Awaiting approval.",
            "status": "waiting",
        }
        statuses["reflection_memory"] = {
            "label": labels["reflection_memory"],
            "active": False,
            "tone": "approval",
            "detail": "Reflection will finalize after approval.",
            "status": "recorded",
        }
    elif trace.execution_status:
        statuses["execution"] = {
            "label": labels["execution"],
            "active": False,
            "tone": "complete",
            "detail": _titleize(trace.execution_status),
            "status": trace.execution_status,
        }
        statuses["reflection_memory"] = {
            "label": labels["reflection_memory"],
            "active": False,
            "tone": "complete",
            "detail": "Recorded" if state.memory and state.memory.reflection_notes else "Pending",
            "status": "recorded" if state.memory and state.memory.reflection_notes else "pending",
        }
    return statuses


def candidate_plan_dataframe(state: SystemState) -> pd.DataFrame:
    if not state.decision_logs:
        return pd.DataFrame(columns=["strategy", "score", "approval_required", "selected"])
    decision = state.decision_logs[-1]
    selected = state.latest_plan.strategy_label if state.latest_plan else None
    return pd.DataFrame(
        [
            {
                "strategy": item.strategy_label,
                "score": item.score,
                "approval_required": item.approval_required,
                "selected": item.strategy_label == selected,
            }
            for item in decision.candidate_evaluations
        ]
    )


def candidate_score_breakdown_dataframe(evaluation: CandidatePlanEvaluation) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"factor": _titleize(key), "value": value}
            for key, value in evaluation.score_breakdown.items()
        ]
    )


def render_score_breakdown(log: DecisionLog) -> None:
    frame = pd.DataFrame(
        [
            {"factor": _titleize(key), "value": value}
            for key, value in log.score_breakdown.items()
        ]
    )
    styled_table(frame)


def memory_tables(state: SystemState) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    memory = state.memory
    supplier_frame = pd.DataFrame(
        [
            {"Supplier": supplier_id, "Reliability": reliability}
            for supplier_id, reliability in (memory.supplier_reliability.items() if memory else [])
        ]
    )
    route_frame = pd.DataFrame(
        [
            {"Route": route_id, "Disruption Prior": prior}
            for route_id, prior in (memory.route_disruption_priors.items() if memory else [])
        ]
    )
    scenario_frame = pd.DataFrame(
        [
            {
                "Run": run.run_id,
                "Scenario": run.scenario_id,
                "Decision": run.decision_id,
                "Approval": run.approval_status,
                "Reflection": run.reflection_status,
                "Status": run.status,
            }
            for run in reversed(state.scenario_history)
        ]
    )
    return supplier_frame, route_frame, scenario_frame


def latest_reflection_snapshot(state: SystemState) -> dict[str, object] | None:
    notes = state.memory.reflection_notes if state.memory else []
    if not notes:
        return None
    note = notes[-1]
    return {
        "note_id": note.note_id,
        "summary": note.summary,
        "pattern_tags": note.pattern_tags,
        "lessons": note.lessons,
        "follow_up_checks": note.follow_up_checks,
        "scenario_id": note.scenario_id,
        "llm_error": note.llm_error,
    }


def reflection_timeline_dataframe(state: SystemState) -> pd.DataFrame:
    notes = state.memory.reflection_notes if state.memory else []
    return pd.DataFrame(
        [
            {
                "note_id": note.note_id,
                "scenario_id": note.scenario_id,
                "approval_status": note.approval_status,
                "summary": note.summary,
            }
            for note in reversed(notes)
        ]
    )


def _planner_input_summary(state: SystemState) -> list[dict[str, str]]:
    trace = state.latest_trace
    latest_decision = state.decision_logs[-1] if state.decision_logs else None
    return [
        {
            "field": "Candidate plans",
            "value": str(len(latest_decision.candidate_evaluations)) if latest_decision else "0",
        },
        {
            "field": "Selected strategy",
            "value": trace.selected_strategy if trace and trace.selected_strategy else "not selected",
        },
        {
            "field": "Operating mode",
            "value": state.mode.value,
        },
    ]


def agent_node_payload(state: SystemState, node_key: str) -> dict[str, object]:
    trace = state.latest_trace
    proposal = state.agent_outputs.get(node_key)
    step = next((item for item in trace.steps if item.node_key == node_key), None) if trace else None
    title = pipeline_node_labels().get(node_key, _titleize(node_key))
    observations = list(step.observations if step else [])
    if proposal:
        observations.extend(item for item in proposal.observations if item not in observations)
    tradeoffs = list(step.tradeoffs if step else [])
    if proposal:
        tradeoffs.extend(item for item in proposal.tradeoffs if item not in tradeoffs)
    recommended_actions = list(step.recommended_action_ids if step else [])
    if proposal:
        recommended_actions.extend(
            item for item in proposal.recommended_action_ids if item not in recommended_actions
        )
    risks = list(step.risks if step else [])
    if proposal:
        risks.extend(item for item in proposal.risks if item not in risks)

    if node_key == "planner":
        input_rows = _planner_input_summary(state)
    else:
        input_rows = [
            {"field": "Mode", "value": step.mode_snapshot if step else state.mode.value},
            {"field": "Status", "value": step.status if step else "unknown"},
        ]

    return {
        "title": title,
        "summary": (step.summary if step and step.summary else proposal.domain_summary if proposal else ""),
        "reasoning_source": step.reasoning_source if step else "",
        "input_summary": pd.DataFrame(input_rows),
        "observations": observations,
        "recommended_action_ids": recommended_actions,
        "key_factors": observations or risks,
        "recommended_actions": recommended_actions,
        "tradeoffs": tradeoffs,
        "llm_used": bool((step and step.llm_used) or (proposal and proposal.llm_used)),
        "llm_error": step.llm_error if step and step.llm_error else proposal.llm_error if proposal else None,
    }
