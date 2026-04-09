from __future__ import annotations

import pandas as pd
import streamlit as st

from core.enums import ActionType, ApprovalStatus, Mode
from core.models import CandidatePlanEvaluation, DecisionLog, KPIState, Plan, ReflectionNote, SystemState


PIPELINE_NODES = [
    ("risk", "Risk Agent"),
    ("demand", "Demand Agent"),
    ("inventory", "Inventory Agent"),
    ("supplier", "Supplier Agent"),
    ("logistics", "Logistics Agent"),
    ("planner", "Planner Agent"),
    ("critic", "Critic Agent"),
    ("decision_engine", "Decision Engine"),
    ("approval_gate", "Approval Gate"),
    ("execution", "Execution"),
    ("reflection_memory", "Reflection / Memory"),
]


PIPELINE_LABELS = {key: label for key, label in PIPELINE_NODES}


def render_kpis(state: SystemState) -> None:
    cols = st.columns(5)
    cols[0].metric("Service Level", f"{state.kpis.service_level:.1%}")
    cols[1].metric("Total Cost", f"{state.kpis.total_cost:,.0f}")
    cols[2].metric("Disruption Risk", f"{state.kpis.disruption_risk:.1%}")
    cols[3].metric("Recovery Speed", f"{state.kpis.recovery_speed:.1%}")
    cols[4].metric("Stockout Risk", f"{state.kpis.stockout_risk:.1%}")


def mode_summary(state: SystemState) -> dict[str, str]:
    if state.mode == Mode.NORMAL:
        return {
            "label": "Normal Mode",
            "tone": "success",
            "message": "Cost-optimized daily control tower operations are active.",
        }
    if state.mode == Mode.CRISIS:
        return {
            "label": "Crisis Mode",
            "tone": "warning",
            "message": "The system detected a disruption and is prioritizing recovery and resilience.",
        }
    return {
        "label": "Approval Mode",
        "tone": "error",
        "message": "A high-risk recovery plan is waiting for human approval before execution.",
    }


def selected_action_summary(plan: Plan | None) -> dict[str, str] | None:
    if plan is None or not plan.actions:
        return None
    action = next(
        (item for item in plan.actions if item.action_type != ActionType.NO_OP),
        plan.actions[0],
    )
    return {
        "action_id": action.action_id,
        "title": f"{action.action_type.value.replace('_', ' ').title()} for {action.target_id}",
        "detail": action.reason or "No additional explanation provided.",
        "impact": (
            f"Service {action.estimated_service_delta:+.2f} | "
            f"Risk {action.estimated_risk_delta:+.2f} | "
            f"Cost {action.estimated_cost_delta:+.2f}"
        ),
    }


def demo_flow_dataframe(state: SystemState) -> pd.DataFrame:
    latest = state.decision_logs[-1] if state.decision_logs else None
    approval_state = "not required"
    if latest and latest.approval_required:
        approval_state = (
            "waiting for approval"
            if state.pending_plan is not None
            else latest.approval_status.value.replace("_", " ")
        )
    rows = [
        {
            "step": "1. Daily plan",
            "status": "complete" if latest else "pending",
            "detail": "Normal-mode optimized plan built" if latest else "Run the daily plan to begin.",
        },
        {
            "step": "2. Disruption detected",
            "status": "complete" if state.active_events else "pending",
            "detail": (
                ", ".join(event.type.value for event in state.active_events)
                if state.active_events
                else "No active disruption events."
            ),
        },
        {
            "step": "3. Autonomous replan",
            "status": "complete" if latest and latest.event_ids else "pending",
            "detail": (
                f"Plan {latest.plan_id} selected in {state.mode.value} mode"
                if latest and latest.event_ids
                else "Waiting for a disruption-triggered replan."
            ),
        },
        {
            "step": "4. Approval workflow",
            "status": approval_state,
            "detail": latest.approval_reason if latest and latest.approval_reason else "No approval gate active.",
        },
        {
            "step": "5. Learn from outcomes",
            "status": "complete" if state.scenario_history else "pending",
            "detail": (
                f"{len(state.scenario_history)} scenario run(s) recorded in memory"
                if state.scenario_history
                else "No scenario outcomes recorded yet."
            ),
        },
    ]
    return pd.DataFrame(rows)


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


def event_feed_dataframe(state: SystemState) -> pd.DataFrame:
    if not state.active_events:
        return pd.DataFrame(columns=["event_id", "type", "severity", "entities", "detail"])
    return pd.DataFrame(
        [
            {
                "event_id": event.event_id,
                "type": event.type.value,
                "severity": round(event.severity, 2),
                "entities": ", ".join(event.entity_ids),
                "detail": ", ".join(f"{key}={value}" for key, value in event.payload.items()),
            }
            for event in state.active_events
        ]
    )


def decision_log_dataframe(state: SystemState) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "decision_id": log.decision_id,
                "plan_id": log.plan_id,
                "approval_required": log.approval_required,
                "approval_reason": log.approval_reason,
                "approval_status": log.approval_status.value,
                "service_level_after": log.after_kpis.service_level,
                "total_cost_after": log.after_kpis.total_cost,
                "rationale": log.rationale,
            }
            for log in reversed(state.decision_logs)
        ]
    )


def decision_log_summary_dataframe(logs: list[DecisionLog]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "decision_id": log.decision_id,
                "plan_id": log.plan_id,
                "approval_status": approval_badge_text(log),
                "approval_required": log.approval_required,
                "service_level_after": log.after_kpis.service_level,
                "total_cost_after": log.after_kpis.total_cost,
            }
            for log in logs
        ]
    )


def kpi_comparison_dataframe(decision_log: DecisionLog) -> pd.DataFrame:
    before = decision_log.before_kpis
    after = decision_log.after_kpis
    return pd.DataFrame(
        [
            {
                "metric": "service_level",
                "before": before.service_level,
                "after": after.service_level,
                "delta": round(after.service_level - before.service_level, 4),
            },
            {
                "metric": "total_cost",
                "before": before.total_cost,
                "after": after.total_cost,
                "delta": round(after.total_cost - before.total_cost, 2),
            },
            {
                "metric": "disruption_risk",
                "before": before.disruption_risk,
                "after": after.disruption_risk,
                "delta": round(after.disruption_risk - before.disruption_risk, 4),
            },
            {
                "metric": "recovery_speed",
                "before": before.recovery_speed,
                "after": after.recovery_speed,
                "delta": round(after.recovery_speed - before.recovery_speed, 4),
            },
        ]
    )


def kpi_delta_dataframe(before: KPIState, after: KPIState) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "metric": "service_level",
                "before": before.service_level,
                "after": after.service_level,
                "delta": round(after.service_level - before.service_level, 4),
            },
            {
                "metric": "total_cost",
                "before": before.total_cost,
                "after": after.total_cost,
                "delta": round(after.total_cost - before.total_cost, 2),
            },
            {
                "metric": "disruption_risk",
                "before": before.disruption_risk,
                "after": after.disruption_risk,
                "delta": round(after.disruption_risk - before.disruption_risk, 4),
            },
            {
                "metric": "recovery_speed",
                "before": before.recovery_speed,
                "after": after.recovery_speed,
                "delta": round(after.recovery_speed - before.recovery_speed, 4),
            },
            {
                "metric": "stockout_risk",
                "before": before.stockout_risk,
                "after": after.stockout_risk,
                "delta": round(after.stockout_risk - before.stockout_risk, 4),
            },
        ]
    )


def kpi_state_dataframe(kpis: KPIState) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"metric": "service_level", "value": kpis.service_level},
            {"metric": "total_cost", "value": kpis.total_cost},
            {"metric": "disruption_risk", "value": kpis.disruption_risk},
            {"metric": "recovery_speed", "value": kpis.recovery_speed},
            {"metric": "stockout_risk", "value": kpis.stockout_risk},
            {"metric": "decision_latency_ms", "value": kpis.decision_latency_ms},
        ]
    )


def plan_actions_dataframe(plan: Plan) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "action_id": action.action_id,
                "type": action.action_type.value,
                "target_id": action.target_id,
                "estimated_cost_delta": action.estimated_cost_delta,
                "estimated_risk_delta": action.estimated_risk_delta,
                "estimated_recovery_hours": action.estimated_recovery_hours,
                "reason": action.reason,
            }
            for action in plan.actions
        ]
    )


def score_breakdown_dataframe(decision_log: DecisionLog) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"component": component, "contribution": contribution}
            for component, contribution in decision_log.score_breakdown.items()
        ]
    )


def rejected_actions_dataframe(decision_log: DecisionLog) -> pd.DataFrame:
    return pd.DataFrame(decision_log.rejected_actions)


def memory_summary_tables(state: SystemState) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    memory = state.memory
    supplier_rows = []
    route_rows = []
    scenario_rows = []
    if memory:
        supplier_rows = [
            {"supplier_id": supplier_id, "learned_reliability": reliability}
            for supplier_id, reliability in memory.supplier_reliability.items()
        ]
        route_rows = [
            {"route_id": route_id, "disruption_prior": prior}
            for route_id, prior in memory.route_disruption_priors.items()
        ]
        scenario_rows = [
            {
                "scenario_id": scenario_id,
                "runs": details.get("runs", 0),
                "latest_run_id": details.get("latest_run_id"),
                "latest_plan_id": details.get("latest_plan_id"),
                "latest_approval_status": details.get("latest_approval_status"),
            }
            for scenario_id, details in memory.scenario_outcomes.items()
        ]
    return (
        pd.DataFrame(supplier_rows),
        pd.DataFrame(route_rows),
        pd.DataFrame(scenario_rows),
    )


def approval_badge_text(decision_log: DecisionLog | None) -> str:
    if decision_log is None:
        return "No approval activity yet"
    if decision_log.approval_status == ApprovalStatus.PENDING:
        return "Approval pending"
    return f"Approval {decision_log.approval_status.value.replace('_', ' ')}"


def pipeline_node_labels() -> dict[str, str]:
    return PIPELINE_LABELS.copy()


def _latest_decision(state: SystemState) -> DecisionLog | None:
    return state.decision_logs[-1] if state.decision_logs else None


def _latest_reflection_note(state: SystemState) -> ReflectionNote | None:
    if state.memory and state.memory.reflection_notes:
        return state.memory.reflection_notes[-1]
    return None


def _latest_scenario_run(state: SystemState):
    return state.scenario_history[-1] if state.scenario_history else None


def pipeline_node_status_map(state: SystemState) -> dict[str, dict[str, str]]:
    latest_decision = _latest_decision(state)
    latest_run = _latest_scenario_run(state)
    crisis_like = state.mode in {Mode.CRISIS, Mode.APPROVAL}
    statuses: dict[str, dict[str, str]] = {}
    for key, label in PIPELINE_NODES:
        active = False
        tone = "idle"
        detail = "No activity yet."
        if key in state.agent_outputs:
            active = True
            tone = "crisis" if crisis_like else "normal"
            detail = state.agent_outputs[key].domain_summary or state.agent_outputs[key].notes_for_planner or "Agent executed this cycle."
        elif key == "decision_engine" and latest_decision is not None:
            active = True
            tone = "approval" if latest_decision.approval_required else ("crisis" if crisis_like else "normal")
            detail = latest_decision.selection_reason or "Deterministic scoring selected the final plan."
        elif key == "approval_gate" and latest_decision is not None:
            active = latest_decision.approval_required or latest_decision.approval_status == ApprovalStatus.PENDING
            if latest_decision.approval_status == ApprovalStatus.PENDING:
                tone = "approval"
                detail = latest_decision.approval_reason or "Waiting for operator approval."
            elif latest_decision.approval_required:
                tone = "executed"
                detail = approval_badge_text(latest_decision)
        elif key == "execution" and latest_decision is not None:
            active = latest_decision.approval_status in {
                ApprovalStatus.AUTO_APPLIED,
                ApprovalStatus.APPROVED,
            }
            if active:
                tone = "executed"
                detail = f"Executed {len(latest_decision.selected_actions)} selected action(s)."
        elif key == "reflection_memory" and latest_run is not None:
            active = True
            if latest_run.reflection_status == "completed":
                tone = "learning"
                detail = "Outcome captured and reflection memory written."
            elif latest_run.reflection_status == "pending_approval":
                tone = "approval"
                detail = "Learning is waiting for approval before final reflection."
            else:
                tone = "idle"
                detail = "Scenario history updated without finalized reflection."
        statuses[key] = {
            "label": label,
            "active": "yes" if active else "no",
            "tone": tone,
            "detail": detail,
        }
    return statuses


def pipeline_graph_source(state: SystemState) -> str:
    statuses = pipeline_node_status_map(state)
    fill_map = {
        "idle": "#e5e7eb",
        "normal": "#d1fae5",
        "crisis": "#fde68a",
        "approval": "#fecaca",
        "executed": "#bfdbfe",
        "learning": "#ddd6fe",
    }
    lines = [
        "digraph ChainCopilot {",
        'rankdir=LR;',
        'graph [fontname="Helvetica", bgcolor="transparent", nodesep="0.4", ranksep="0.6"];',
        'node [shape=box, style="rounded,filled", fontname="Helvetica", color="#1f2937", penwidth=1.5];',
        'edge [color="#6b7280", penwidth=1.4, arrowsize=0.8];',
    ]
    for key, label in PIPELINE_NODES:
        tone = statuses[key]["tone"]
        detail = statuses[key]["detail"].replace('"', "'")
        fill = fill_map[tone]
        border = "#111827" if statuses[key]["active"] == "yes" else "#9ca3af"
        node_label = f"{label}\\n{detail[:48]}"
        lines.append(
            f'{key} [label="{node_label}", fillcolor="{fill}", color="{border}"];'
        )

    lines.extend(
        [
            "risk -> demand -> inventory -> supplier -> logistics -> planner -> critic -> decision_engine;",
            'decision_engine -> approval_gate [label="high risk", color="#dc2626"];',
            'decision_engine -> execution [label="auto apply", color="#2563eb"];',
            'approval_gate -> execution [label="approved", color="#ea580c"];',
            'execution -> reflection_memory [label="learn", color="#7c3aed"];',
        ]
    )
    lines.append("}")
    return "\n".join(lines)


def candidate_plan_dataframe(state: SystemState) -> pd.DataFrame:
    latest_decision = _latest_decision(state)
    selected_strategy = state.latest_plan.strategy_label if state.latest_plan else None
    if latest_decision is None or not latest_decision.candidate_evaluations:
        return pd.DataFrame(
            columns=[
                "strategy",
                "selected",
                "score",
                "service_level",
                "total_cost",
                "disruption_risk",
                "recovery_speed",
                "approval_required",
                "source",
                "rationale",
            ]
        )
    rows = []
    for evaluation in latest_decision.candidate_evaluations:
        rows.append(
            {
                "strategy": evaluation.strategy_label,
                "selected": evaluation.strategy_label == selected_strategy,
                "score": evaluation.score,
                "service_level": evaluation.projected_kpis.service_level,
                "total_cost": evaluation.projected_kpis.total_cost,
                "disruption_risk": evaluation.projected_kpis.disruption_risk,
                "recovery_speed": evaluation.projected_kpis.recovery_speed,
                "approval_required": evaluation.approval_required,
                "source": "AI" if evaluation.llm_used else "Fallback",
                "rationale": evaluation.rationale,
            }
        )
    return pd.DataFrame(rows)


def candidate_score_breakdown_dataframe(evaluation: CandidatePlanEvaluation) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"component": component, "contribution": contribution}
            for component, contribution in evaluation.score_breakdown.items()
        ]
    )


def reflection_timeline_dataframe(state: SystemState) -> pd.DataFrame:
    memory = state.memory
    if memory is None or not memory.reflection_notes:
        return pd.DataFrame(columns=["run_id", "scenario_id", "approval_status", "summary", "tags"])
    return pd.DataFrame(
        [
            {
                "run_id": note.run_id,
                "scenario_id": note.scenario_id,
                "approval_status": note.approval_status,
                "summary": note.summary,
                "tags": ", ".join(note.pattern_tags),
            }
            for note in reversed(memory.reflection_notes)
        ]
    )


def latest_reflection_snapshot(state: SystemState) -> dict[str, object] | None:
    note = _latest_reflection_note(state)
    if note is None:
        return None
    return {
        "summary": note.summary,
        "lessons": note.lessons,
        "pattern_tags": note.pattern_tags,
        "follow_up_checks": note.follow_up_checks,
        "approval_status": note.approval_status,
        "llm_used": note.llm_used,
        "llm_error": note.llm_error,
    }


def _agent_output_block(state: SystemState, node_key: str) -> tuple[str, list[str], list[str], list[str], bool, str | None]:
    output = state.agent_outputs.get(node_key)
    if output is None:
        return "", [], [], [], False, None
    summary = output.domain_summary or output.notes_for_planner
    factors = output.downstream_impacts or output.observations
    actions = output.recommended_action_ids
    tradeoffs = output.tradeoffs or output.risks
    return summary, factors, actions, tradeoffs, output.llm_used, output.llm_error


def agent_node_payload(state: SystemState, node_key: str) -> dict[str, object]:
    latest_decision = _latest_decision(state)
    latest_run = _latest_scenario_run(state)
    latest_note = _latest_reflection_note(state)
    labels = pipeline_node_labels()
    mode_label = mode_summary(state)["label"]
    active_events = ", ".join(event.type.value for event in state.active_events) or "none"
    base_inputs = [
        {"field": "Mode", "value": mode_label},
        {"field": "Active events", "value": active_events},
        {"field": "Service level", "value": f"{state.kpis.service_level:.1%}"},
        {"field": "Disruption risk", "value": f"{state.kpis.disruption_risk:.1%}"},
    ]
    summary = ""
    factors: list[str] = []
    actions: list[str] = []
    tradeoffs: list[str] = []
    llm_used = False
    llm_error: str | None = None
    reasoning_source = "No reasoning captured yet."

    if node_key in {"risk", "demand", "inventory", "supplier", "logistics", "planner", "critic"}:
        summary, factors, actions, tradeoffs, llm_used, llm_error = _agent_output_block(state, node_key)
        reasoning_source = "AI-assisted reasoning" if llm_used else "Deterministic or fallback reasoning"
    elif node_key == "decision_engine" and latest_decision is not None:
        summary = latest_decision.selection_reason or "Decision engine selected the highest-scoring plan."
        factors = latest_decision.winning_factors
        actions = latest_decision.selected_actions
        tradeoffs = [latest_decision.approval_reason] if latest_decision.approval_reason else []
        reasoning_source = "Deterministic policy engine"
    elif node_key == "approval_gate" and latest_decision is not None:
        summary = latest_decision.approval_reason or "No approval required."
        factors = [approval_badge_text(latest_decision)]
        if latest_decision.llm_approval_summary:
            tradeoffs = [latest_decision.llm_approval_summary]
            llm_used = True
        reasoning_source = "Human approval guardrail"
    elif node_key == "execution" and state.latest_plan is not None:
        summary = (
            f"Applied strategy {state.latest_plan.strategy_label or 'n/a'} with status {state.latest_plan.status.value}."
        )
        actions = [action.action_id for action in state.latest_plan.actions]
        factors = [selected_action_summary(state.latest_plan)["detail"]] if selected_action_summary(state.latest_plan) else []
        reasoning_source = "Deterministic execution guards"
    elif node_key == "reflection_memory":
        if latest_note is not None:
            summary = latest_note.summary
            factors = latest_note.lessons
            actions = latest_note.pattern_tags
            tradeoffs = latest_note.follow_up_checks
            llm_used = latest_note.llm_used
            llm_error = latest_note.llm_error
            reasoning_source = "AI reflection memory" if llm_used else "Deterministic reflection fallback"
        elif latest_run is not None:
            summary = f"Latest run is {latest_run.reflection_status}."
            factors = [latest_run.scenario_id]
            reasoning_source = "Reflection pending final outcome"

    extra_inputs = list(base_inputs)
    if node_key == "planner" and latest_decision is not None:
        extra_inputs.extend(
            [
                {"field": "Candidate plans", "value": str(len(latest_decision.candidate_evaluations))},
                {"field": "Selected strategy", "value": state.latest_plan.strategy_label if state.latest_plan else "n/a"},
                {"field": "Planner source", "value": state.latest_plan.generated_by if state.latest_plan else "n/a"},
            ]
        )
    elif node_key == "critic" and latest_decision is not None:
        extra_inputs.extend(
            [
                {"field": "Selected strategy", "value": state.latest_plan.strategy_label if state.latest_plan else "n/a"},
                {"field": "Critic used", "value": "yes" if latest_decision.critic_used else "no"},
            ]
        )
    elif node_key == "reflection_memory" and latest_run is not None:
        extra_inputs.extend(
            [
                {"field": "Latest scenario", "value": latest_run.scenario_id},
                {"field": "Reflection status", "value": latest_run.reflection_status},
            ]
        )

    return {
        "title": labels[node_key],
        "input_summary": pd.DataFrame(extra_inputs),
        "summary": summary or "No detailed summary recorded for this node.",
        "key_factors": factors,
        "recommended_actions": actions,
        "tradeoffs": tradeoffs,
        "reasoning_source": reasoning_source,
        "llm_used": llm_used,
        "llm_error": llm_error,
    }
