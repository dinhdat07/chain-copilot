from __future__ import annotations

from app_api.services import action_view, execution_record_view, latest_trace_view, run_record_view
from core.display_text import normalize_display_text
from core.enums import ActionType
from core.models import Action, OrchestrationTrace, TraceRouteDecision, TraceStep
from core.runtime_records import (
    DispatchMode,
    ExecutionReceipt,
    ExecutionRecord,
    ExecutionStatus,
    ExecutionTransition,
    RunRecord,
    RunStatus,
    RunType,
    SelectedPlanSummary,
)
from core.state import load_initial_state, utc_now


def test_normalize_display_text_caps_lowercase_display_strings() -> None:
    assert normalize_display_text("because inventory is low.") == "Because inventory is low."
    assert normalize_display_text("  - because inventory is low.") == "  - Because inventory is low."
    assert normalize_display_text("1. because inventory is low.") == "1. Because inventory is low."
    assert normalize_display_text('"because inventory is low."') == '"Because inventory is low."'


def test_normalize_display_text_preserves_already_correct_and_identifier_led_values() -> None:
    assert normalize_display_text("Because inventory is low.") == "Because inventory is low."
    assert normalize_display_text("SKU_001 remains exposed.") == "SKU_001 remains exposed."
    assert normalize_display_text("sku_001 remains exposed.") == "sku_001 remains exposed."
    assert normalize_display_text("`because inventory is low.`") == "`because inventory is low.`"


def test_action_view_normalizes_reason() -> None:
    view = action_view(
        Action(
            action_id="action_1",
            action_type=ActionType.REORDER,
            target_id="SKU_001",
            parameters={},
            estimated_cost_delta=10.0,
            estimated_service_delta=0.05,
            estimated_risk_delta=-0.1,
            estimated_recovery_hours=12.0,
            reason="reorder is needed because inventory is low.",
            priority=1.0,
        )
    )

    assert view.reason == "Reorder is needed because inventory is low."


def test_latest_trace_view_normalizes_trace_display_fields() -> None:
    state = load_initial_state()
    now = utc_now()
    state.latest_trace = OrchestrationTrace(
        trace_id="trace_1",
        run_id="run_1",
        started_at=now,
        mode_before=state.mode.value,
        current_branch="normal",
        route_decisions=[
            TraceRouteDecision(
                from_node="risk",
                outcome="continue",
                to_node="planner",
                reason="route chosen after supplier delay review",
            )
        ],
        steps=[
            TraceStep(
                step_id="step_1",
                sequence=1,
                node_key="risk",
                node_type="agent",
                started_at=now,
                completed_at=now,
                mode_snapshot=state.mode.value,
                summary="risk review complete",
                observations=["delay detected at supplier sup_a"],
                risks=["service level may degrade if no action is taken"],
                downstream_impacts=["downstream fulfillment may slip by one day"],
                tradeoffs=["faster response may cost more"],
                llm_error="fallback triggered due to timeout",
                fallback_used=True,
                fallback_reason="fallback triggered due to timeout",
            )
        ],
        selection_reason="selected because it reduces stockout risk fastest",
        approval_reason="manual review required for high severity disruption",
        critic_summary="plan still depends on a fragile supplier",
    )

    view = latest_trace_view(state)

    assert view.steps[0].summary == "Risk review complete"
    assert view.steps[0].observations == ["Delay detected at supplier sup_a"]
    assert view.steps[0].risks == ["Service level may degrade if no action is taken"]
    assert view.steps[0].downstream_impacts == ["Downstream fulfillment may slip by one day"]
    assert view.steps[0].tradeoffs == ["Faster response may cost more"]
    assert view.steps[0].llm_error == "Fallback triggered due to timeout"
    assert view.steps[0].fallback_reason == "Fallback triggered due to timeout"
    assert view.route_decisions[0].reason == "Route chosen after supplier delay review"
    assert view.selection_reason == "Selected because it reduces stockout risk fastest"
    assert view.approval_reason == "Manual review required for high severity disruption"
    assert view.critic_summary == "Plan still depends on a fragile supplier"


def test_run_and_execution_views_normalize_nested_display_fields() -> None:
    now = utc_now()
    run_view = run_record_view(
        RunRecord(
            run_id="run_1",
            run_type=RunType.DAILY_CYCLE,
            correlation_id="corr_1",
            mode_before="normal",
            mode_after="normal",
            status=RunStatus.COMPLETED,
            started_at=now,
            completed_at=now,
            llm_fallback_used=True,
            llm_fallback_reason="planner fell back after timeout",
            selected_plan_summary=SelectedPlanSummary(
                plan_id="plan_1",
                strategy_label="cost_first",
                generated_by="llm_planner",
                approval_required=True,
                approval_reason="manual review required after critic findings",
                score=0.42,
                action_ids=["action_1"],
            ),
        )
    )
    assert run_view.llm_fallback_reason == "Planner fell back after timeout"
    assert (
        run_view.selected_plan_summary.approval_reason
        == "Manual review required after critic findings"
    )

    execution_view = execution_record_view(
        ExecutionRecord(
            execution_id="exec_1",
            run_id="run_1",
            status=ExecutionStatus.APPROVED,
            dispatch_mode=DispatchMode.SIMULATION,
            target_system="digital_twin",
            action_ids=["action_1"],
            receipts=[
                ExecutionReceipt(
                    receipt_id="receipt_1",
                    action_id="action_1",
                    status="accepted",
                    detail="dispatch queued in sandbox",
                )
            ],
            status_history=[
                ExecutionTransition(
                    status=ExecutionStatus.APPROVED,
                    timestamp=now,
                    reason="operator approved execution",
                )
            ],
            failure_reason="adapter timeout while posting to target system",
            created_at=now,
            updated_at=now,
        )
    )
    assert execution_view.receipts[0].detail == "Dispatch queued in sandbox"
    assert execution_view.status_history[0].reason == "Operator approved execution"
    assert execution_view.failure_reason == "Adapter timeout while posting to target system"
