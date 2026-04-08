from __future__ import annotations

import pandas as pd
import streamlit as st

from core.enums import ActionType, ApprovalStatus, Mode
from core.models import DecisionLog, KPIState, Plan, SystemState


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
