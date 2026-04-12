from __future__ import annotations

import pandas as pd
import streamlit as st

from core.enums import ActionType, ApprovalStatus, Mode
from core.models import KPIState, Plan, SystemState


def render_kpis(state: SystemState) -> None:
    cols = st.columns(5)
    cols[0].metric("Service Level", f"{state.kpis.service_level:.1%}")
    cols[1].metric("Total Cost", f"{state.kpis.total_cost:,.0f}")
    cols[2].metric("Disruption Risk", f"{state.kpis.disruption_risk:.1%}")
    cols[3].metric("Recovery Speed", f"{state.kpis.recovery_speed:.1%}")
    cols[4].metric("Stockout Risk", f"{state.kpis.stockout_risk:.1%}")


def inventory_dataframe(state: SystemState) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sku": item.sku,
                "on_hand": item.on_hand,
                "incoming_qty": item.incoming_qty,
                "forecast_qty": item.forecast_qty,
                "preferred_supplier_id": item.preferred_supplier_id,
                "preferred_route_id": item.preferred_route_id,
            }
            for item in state.inventory.values()
        ]
    )


def decision_log_dataframe(state: SystemState) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "decision_id": log.decision_id,
                "plan_id": log.plan_id,
                "approval_status": log.approval_status.value,
                "service_level_after": log.after_kpis.service_level,
                "total_cost_after": log.after_kpis.total_cost,
                "rationale": log.rationale,
            }
            for log in reversed(state.decision_logs)
        ]
    )


def mode_summary(state: SystemState) -> dict[str, str]:
    mapping = {
        Mode.NORMAL: {"label": "Normal Mode", "tone": "success"},
        Mode.CRISIS: {"label": "Crisis Mode", "tone": "warning"},
        Mode.APPROVAL: {"label": "Approval Mode", "tone": "warning"},
    }
    return mapping.get(state.mode, {"label": str(state.mode).title(), "tone": "neutral"})


def selected_action_summary(plan: Plan | None) -> dict[str, str] | None:
    if plan is None or not plan.actions:
        return None
    selected = next(
        (action for action in plan.actions if action.action_type != ActionType.NO_OP),
        plan.actions[0],
    )
    return {
        "title": f"{selected.action_type.value.replace('_', ' ').title()} {selected.target_id}",
        "impact": (
            f"Service {selected.estimated_service_delta:+.0%}, "
            f"Cost {selected.estimated_cost_delta:+.0f}, "
            f"Risk {selected.estimated_risk_delta:+.0%}"
        ),
        "reason": selected.reason,
    }


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


def pipeline_node_status_map(state: SystemState) -> dict[str, dict[str, str]]:
    trace = state.latest_trace
    statuses: dict[str, dict[str, str]] = {
        "risk_agent": {"status": "idle", "tone": "normal"},
        "demand_agent": {"status": "idle", "tone": "normal"},
        "inventory_agent": {"status": "idle", "tone": "normal"},
        "supplier_agent": {"status": "idle", "tone": "normal"},
        "logistics_agent": {"status": "idle", "tone": "normal"},
        "planner_agent": {"status": "idle", "tone": "normal"},
        "critic_agent": {"status": "idle", "tone": "normal"},
        "decision_engine": {"status": "idle", "tone": "normal"},
        "approval_gate": {"status": "idle", "tone": "normal"},
        "execution": {"status": "idle", "tone": "normal"},
        "reflection_memory": {"status": "idle", "tone": "normal"},
    }
    if trace is None:
        return statuses
    completed_nodes = {
        step.node_key: step.status
        for step in trace.steps
    }
    for node_key in list(statuses):
        normalized = node_key.replace("_agent", "")
        if normalized in completed_nodes:
            statuses[node_key] = {"status": completed_nodes[normalized], "tone": "complete"}
    statuses["decision_engine"] = {"status": "completed", "tone": "complete"}
    if trace.terminal_stage == "approval":
        statuses["approval_gate"] = {"status": "waiting", "tone": "approval"}
        statuses["reflection_memory"] = {"status": "recorded", "tone": "approval"}
    elif trace.execution_status:
        statuses["execution"] = {"status": trace.execution_status, "tone": "complete"}
        statuses["reflection_memory"] = {
            "status": "recorded" if state.memory and state.memory.reflection_notes else "pending",
            "tone": "complete",
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
        "scenario_id": note.scenario_id,
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
    if trace is None:
        return {
            "title": node_key.replace("_", " ").title(),
            "summary": "",
            "reasoning_source": "",
            "input_summary": pd.DataFrame(columns=["field", "value"]),
        }
    step = next((item for item in trace.steps if item.node_key == node_key), None)
    title_map = {
        "risk": "Risk Agent",
        "demand": "Demand Agent",
        "inventory": "Inventory Agent",
        "supplier": "Supplier Agent",
        "logistics": "Logistics Agent",
        "planner": "Planner Agent",
        "critic": "Critic Agent",
    }
    input_rows = _planner_input_summary(state) if node_key == "planner" else [
        {"field": "Mode", "value": step.mode_snapshot if step else state.mode.value},
        {"field": "Status", "value": step.status if step else "unknown"},
    ]
    return {
        "title": title_map.get(node_key, node_key.replace("_", " ").title()),
        "summary": step.summary if step else "",
        "reasoning_source": step.reasoning_source if step else "",
        "input_summary": pd.DataFrame(input_rows),
        "observations": step.observations if step else [],
        "recommended_action_ids": step.recommended_action_ids if step else [],
    }
