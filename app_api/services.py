from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from core.display_text import (
    normalize_display_list,
    normalize_display_payload,
    normalize_display_text,
)
from core.enums import ApprovalStatus, EventType
from core.memory import SQLiteStore
from core.models import (
    Action,
    ConstraintViolation,
    DecisionLog,
    Event,
    OrchestrationTrace,
    Plan,
    SystemState,
)
from core.runtime_records import (
    EventClass,
    EventEnvelope,
    ExecutionRecord,
    ExecutionStatus,
    RunRecord,
    RunStatus,
    RunType,
)
from core.runtime_tracking import (
    advance_execution_record,
    build_execution_record,
    build_run_record,
    clone_trace_for_run,
    new_correlation_id,
    new_event_envelope_id,
    new_run_id,
)
from core.state import (
    clone_state,
    load_initial_state,
    recompute_kpis,
    refresh_operational_baseline,
    state_summary,
    utc_now,
)
from llm.config import load_settings

from orchestrator.graph import build_graph
from orchestrator.service import (
    PendingApprovalError,
    approve_pending_plan,
    request_safer_plan,
    reset_runtime,
    run_daily_plan,
    select_pending_alternative_plan,
)
from simulation.runner import ScenarioRunner
from simulation.scenarios import get_scenario_events, list_scenarios
from execution.dispatch_service import ActionDispatchService
from execution.models import (
    ExecutionRecord as ActionExecutionRecord,
)
from execution.state_machine import (
    compute_overall_progress,
    compute_plan_execution_status,
)

from app_api.schemas import (
    ActionView,
    ActionExecutionRecordView,
    ApprovalCommandResultResponse,
    ApprovalDetailView,
    AlertView,
    AgentStepView,
    CandidateEvaluationView,
    ConstraintViolationView,
    ControlTowerStateResponse,
    ControlTowerSummaryResponse,
    DecisionLogDetailView,
    DecisionLogSummaryView,
    EventEnvelopeView,
    EventIngestRequest,
    EventView,
    ExecutionRecordView,
    ExecutionSummaryView,
    InventoryRowView,
    KPIView,
    PendingApprovalView,
    PlanView,
    ProjectedStateSummaryView,
    ProjectionStepView,
    ReflectionView,
    RunView,
    RouteDecisionView,
    ScenarioOutcomeView,
    SelectedPlanSummaryView,
    ServiceFlagsView,
    ServiceMetricsView,
    ServiceRuntimeView,
    SupplierRowView,
    TraceView,
)


def _error_detail(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": normalize_display_text(message),
        "details": details or {},
        "retryable": retryable,
        "correlation_id": correlation_id,
    }


def raise_not_found(resource: str, resource_id: str) -> None:
    raise HTTPException(
        status_code=404,
        detail=_error_detail(
            code=f"{resource}_not_found",
            message=f"{resource} not found",
            details={"id": resource_id},
        ),
    )


def raise_conflict(message: str, *, code: str = "invalid_state") -> None:
    raise HTTPException(
        status_code=409,
        detail=_error_detail(code=code, message=message, retryable=False),
    )


@dataclass
class ControlTowerRuntime:
    store: SQLiteStore
    state: SystemState
    graph: Any
    runner: ScenarioRunner
    dispatch_service: ActionDispatchService

    @classmethod
    def create(cls, store: SQLiteStore | None = None) -> "ControlTowerRuntime":
        local_store = store or SQLiteStore()
        return cls(
            store=local_store,
            state=refresh_operational_baseline(load_initial_state()),
            graph=build_graph(),
            runner=ScenarioRunner(store=local_store),
            dispatch_service=ActionDispatchService(),
        )

    def reinitialize(self, store: SQLiteStore | None = None) -> None:
        self.store = store or self.store
        self.state = refresh_operational_baseline(load_initial_state())
        self.graph = build_graph()
        self.runner = ScenarioRunner(store=self.store)
        self.dispatch_service = ActionDispatchService()

    def reset(self) -> SystemState:
        self.state = refresh_operational_baseline(reset_runtime(self.store))
        self.graph = build_graph()
        self.runner = ScenarioRunner(store=self.store)
        self.dispatch_service = ActionDispatchService()
        return self.state

    def current_decision_id(self) -> str | None:
        if not self.state.decision_logs:
            return None
        return self.state.decision_logs[-1].decision_id

    def _latest_decision(self) -> DecisionLog | None:
        return self.state.decision_logs[-1] if self.state.decision_logs else None

    def _prepare_approval_trace(self, run_id: str) -> None:
        now = utc_now()
        self.state.run_id = run_id
        self.state.latest_trace = OrchestrationTrace(
            trace_id=f"trace_{uuid4().hex[:8]}",
            run_id=run_id,
            started_at=now,
            mode_before=self.state.mode.value,
            current_branch="approval",
        )

    def _parent_execution_id(self, parent_run_id: str | None) -> str | None:
        if parent_run_id is None:
            return None
        payload = self.store.get_run_record(parent_run_id)
        if payload is None:
            return None
        return payload.get("execution_id")

    def _execution_for_id(self, execution_id: str | None) -> ExecutionRecord | None:
        if execution_id is None:
            return None
        payload = self.store.get_execution_record(execution_id)
        if payload is None:
            return None
        return ExecutionRecord.model_validate(payload)

    def _latest_execution_for_decision(
        self, decision_id: str
    ) -> ExecutionRecord | None:
        matching_runs = [
            item
            for item in self.store.list_run_records(limit=None)
            if item.get("decision_id") == decision_id and item.get("execution_id")
        ]
        if not matching_runs:
            return None
        matching_runs.sort(key=lambda item: item.get("started_at", ""), reverse=True)
        return self._execution_for_id(matching_runs[0].get("execution_id"))

    def _persist_runtime_artifacts(
        self,
        *,
        run_id: str,
        run_type: RunType,
        started_at,
        parent_run_id: str | None,
        envelope: EventEnvelope | None = None,
        execution_record: ExecutionRecord | None = None,
    ) -> tuple[RunRecord, ExecutionRecord | None]:
        decision = self._latest_decision()
        execution = execution_record or build_execution_record(
            run_id=run_id,
            state=self.state,
            decision=decision,
        )
        if execution is not None:
            self.store.save_execution_record(execution)
        run_record = build_run_record(
            run_id=run_id,
            run_type=run_type,
            state=self.state,
            started_at=started_at,
            parent_run_id=parent_run_id,
            envelope=envelope,
            execution_id=execution.execution_id if execution is not None else None,
        )
        self.store.save_run_record(run_record)
        trace = clone_trace_for_run(self.state.latest_trace, run_id)
        if trace is not None:
            self.store.save_trace(run_id, trace)
        self.store.save_state(self.state)
        if decision is not None:
            self.store.save_decision_log(decision)
        return run_record, execution

    def latest_execution(self) -> ExecutionRecord | None:
        latest_run = self.store.get_run_record(self.state.run_id)
        if latest_run is None:
            return None
        return self._execution_for_id(latest_run.get("execution_id"))

    def legacy_response_payload(self) -> dict[str, Any]:
        return {
            "summary": state_summary(self.state),
            "latest_plan": self.state.latest_plan.model_dump(mode="json")
            if self.state.latest_plan
            else None,
            "pending_plan": self.state.pending_plan.model_dump(mode="json")
            if self.state.pending_plan
            else None,
            "decision_id": self.current_decision_id(),
        }

    def run_daily(self) -> SystemState:
        started_at = utc_now()
        parent_run_id = self.state.run_id
        run_id = new_run_id()

        def on_trace_update(trace):
            self.state.latest_trace = trace

        try:
            self.state = run_daily_plan(
                self.state,
                self.store,
                graph=self.graph,
                run_id=run_id,
                trace_updater=on_trace_update,
            )
        except PendingApprovalError as exc:
            raise_conflict(str(exc), code="pending_approval")
        self._persist_runtime_artifacts(
            run_id=run_id,
            run_type=RunType.DAILY_CYCLE,
            started_at=started_at,
            parent_run_id=parent_run_id,
        )
        return self.state

    def ingest_event(self, event: Event) -> SystemState:
        started_at = utc_now()
        parent_run_id = self.state.run_id
        run_id = new_run_id()
        envelope = EventEnvelope(
            event_id=event.event_id,
            event_class=EventClass.DOMAIN,
            event_type=event.type.value,
            source=event.source,
            occurred_at=event.occurred_at,
            ingested_at=event.detected_at,
            correlation_id=new_correlation_id("event"),
            causation_id=None,
            idempotency_key=event.dedupe_key,
            severity=event.severity,
            entity_ids=event.entity_ids,
            payload=event.payload,
        )
        self.store.save_event_envelope(envelope)
        self.state = self.graph.invoke(self.state, event, run_id=run_id)
        self._persist_runtime_artifacts(
            run_id=run_id,
            run_type=RunType.EVENT_RESPONSE,
            started_at=started_at,
            parent_run_id=parent_run_id,
            envelope=envelope,
        )
        return self.state

    def ingest_envelope(
        self, request: EventIngestRequest
    ) -> tuple[EventEnvelope, RunRecord | None, ExecutionRecord | None]:
        occurred_at = request.occurred_at or utc_now()
        ingested_at = utc_now()
        correlation_id = request.correlation_id or new_correlation_id(
            request.event_class.value
        )
        envelope = EventEnvelope(
            event_id=new_event_envelope_id(),
            event_class=request.event_class,
            event_type=request.event_type,
            source=request.source,
            occurred_at=occurred_at,
            ingested_at=ingested_at,
            correlation_id=correlation_id,
            causation_id=request.causation_id,
            idempotency_key=request.idempotency_key
            or f"{request.event_type}:{request.entity_ids}:{request.payload}",
            severity=request.severity,
            entity_ids=request.entity_ids,
            payload=request.payload,
        )
        self.store.save_event_envelope(envelope)
        started_at = ingested_at
        parent_run_id = self.state.run_id
        if request.event_class == EventClass.SYSTEM:
            return envelope, None, None
        if request.event_class == EventClass.COMMAND:
            if request.event_type != "plan_requested":
                raise HTTPException(
                    status_code=422,
                    detail=_error_detail(
                        code="unsupported_command_event",
                        message="command event_type must be plan_requested",
                        correlation_id=correlation_id,
                    ),
                )
            run_id = new_run_id()
            try:
                self.state = run_daily_plan(
                    self.state, self.store, graph=self.graph, run_id=run_id
                )
            except PendingApprovalError as exc:
                raise_conflict(str(exc), code="pending_approval")
            return (
                envelope,
                *self._persist_runtime_artifacts(
                    run_id=run_id,
                    run_type=RunType.DAILY_CYCLE,
                    started_at=started_at,
                    parent_run_id=parent_run_id,
                    envelope=envelope,
                ),
            )
        try:
            event = build_event_from_envelope(envelope)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=_error_detail(
                    code="unsupported_domain_event",
                    message=str(exc),
                    correlation_id=correlation_id,
                ),
            ) from exc
        run_id = new_run_id()
        self.state = self.graph.invoke(self.state, event, run_id=run_id)
        return (
            envelope,
            *self._persist_runtime_artifacts(
                run_id=run_id,
                run_type=RunType.EVENT_RESPONSE,
                started_at=started_at,
                parent_run_id=parent_run_id,
                envelope=envelope,
            ),
        )

    def run_scenario(self, scenario_name: str, seed: int, run_id: str | None = None) -> SystemState:
        if scenario_name not in list_scenarios():
            raise_not_found("scenario", scenario_name)

        def on_trace_update(trace):
            self.state.latest_trace = trace

        try:
            self.state = self.runner.run(
                self.state, scenario_name, seed=seed, trace_updater=on_trace_update, run_id=run_id
            )
        except PendingApprovalError as exc:
            raise_conflict(str(exc), code="pending_approval")
        return self.state

    def approval_command(self, decision_id: str, action: str) -> SystemState:
        started_at = utc_now()
        parent_run_id = self.state.run_id
        run_id = new_run_id()
        self._prepare_approval_trace(run_id)
        parent_execution = self._latest_execution_for_decision(decision_id)
        if parent_execution is None:
            parent_execution = self.latest_execution()
        if parent_execution is None:
            parent_execution = self._execution_for_id(
                self._parent_execution_id(parent_run_id)
            )
        execution_record: ExecutionRecord | None = None
        try:
            if action == "approve":
                self.state = approve_pending_plan(
                    self.state, self.store, decision_id, True, run_id=run_id
                )
                decision = self._latest_decision()
                if parent_execution is not None:
                    execution_record = advance_execution_record(
                        parent_execution,
                        run_id=run_id,
                        decision_id=decision.decision_id if decision else decision_id,
                        plan=self.state.latest_plan,
                        status=ExecutionStatus.APPROVED,
                        reason="operator approved execution; awaiting dispatch",
                    )
            elif action == "reject":
                self.state = approve_pending_plan(
                    self.state, self.store, decision_id, False, run_id=run_id
                )
                decision = self._latest_decision()
                if parent_execution is not None:
                    execution_record = advance_execution_record(
                        parent_execution,
                        run_id=run_id,
                        decision_id=decision.decision_id if decision else decision_id,
                        plan=self.state.latest_plan,
                        status=ExecutionStatus.CANCELLED,
                        reason="operator rejected the pending execution",
                    )
            elif action == "safer_plan":
                self.state = request_safer_plan(
                    self.state, self.store, decision_id, run_id=run_id
                )
                decision = self._latest_decision()
                if parent_execution is not None:
                    cancelled = advance_execution_record(
                        parent_execution,
                        run_id=run_id,
                        decision_id=decision_id,
                        plan=self.state.latest_plan,
                        status=ExecutionStatus.CANCELLED,
                        reason="pending execution superseded by safer plan request",
                    )
                    self.store.save_execution_record(cancelled)
                execution_record = build_execution_record(
                    run_id=run_id,
                    state=self.state,
                    decision=decision,
                )
            else:
                raise HTTPException(
                    status_code=422,
                    detail=_error_detail(
                        code="invalid_approval_action",
                        message="approval action must be approve, reject, or safer_plan",
                    ),
                )
        except ValueError:
            raise_not_found("decision", decision_id)
        except RuntimeError as exc:
            raise_conflict(str(exc), code="approval_conflict")
        self._persist_runtime_artifacts(
            run_id=run_id,
            run_type=RunType.APPROVAL_RESOLUTION,
            started_at=started_at,
            parent_run_id=parent_run_id,
            execution_record=execution_record,
        )
        return self.state

    def select_approval_alternative(
        self, decision_id: str, strategy_label: str
    ) -> SystemState:
        started_at = utc_now()
        parent_run_id = self.state.run_id
        run_id = new_run_id()
        self._prepare_approval_trace(run_id)

        parent_execution = self._latest_execution_for_decision(decision_id)
        if parent_execution is None:
            parent_execution = self.latest_execution()
        if parent_execution is None:
            parent_execution = self._execution_for_id(
                self._parent_execution_id(parent_run_id)
            )

        execution_record: ExecutionRecord | None = None
        try:
            self.state = select_pending_alternative_plan(
                self.state,
                self.store,
                decision_id,
                strategy_label,
                run_id=run_id,
            )
            decision = self._latest_decision()
            if parent_execution is not None:
                cancelled = advance_execution_record(
                    parent_execution,
                    run_id=run_id,
                    decision_id=decision_id,
                    plan=self.state.latest_plan,
                    status=ExecutionStatus.CANCELLED,
                    reason=f"pending execution superseded by selected alternative strategy ({strategy_label})",
                )
                self.store.save_execution_record(cancelled)
            execution_record = build_execution_record(
                run_id=run_id,
                state=self.state,
                decision=decision,
            )
        except ValueError as exc:
            message = str(exc)
            if message.startswith("candidate strategy not found"):
                raise_not_found("candidate_strategy", strategy_label)
            raise_not_found("decision", decision_id)
        except RuntimeError as exc:
            raise_conflict(str(exc), code="approval_conflict")

        self._persist_runtime_artifacts(
            run_id=run_id,
            run_type=RunType.APPROVAL_RESOLUTION,
            started_at=started_at,
            parent_run_id=parent_run_id,
            execution_record=execution_record,
        )
        return self.state

    def what_if(self, scenario_name: str, seed: int) -> dict[str, Any]:
        del seed
        if scenario_name not in list_scenarios():
            raise_not_found("scenario", scenario_name)
        simulated = clone_state(self.state)
        for event in get_scenario_events(scenario_name):
            simulated = self.graph.invoke(simulated, event)
        return {
            "scenario_name": scenario_name,
            "summary": state_summary(simulated),
            "latest_plan": simulated.latest_plan.model_dump(mode="json")
            if simulated.latest_plan
            else None,
        }

    def dispatch_plan(self, plan_id: str, mode: str) -> dict[str, Any]:
        plan = None
        if self.state.latest_plan and self.state.latest_plan.plan_id == plan_id:
            plan = self.state.latest_plan
        elif self.state.pending_plan and self.state.pending_plan.plan_id == plan_id:
            plan = self.state.pending_plan

        if plan is None:
            raise_not_found("plan", plan_id)
        existing_commit_records = [
            ActionExecutionRecord.model_validate(item)
            for item in self.store.list_action_execution_records(limit=None)
            if item.get("plan_id") == plan_id
            and item.get("dispatch_mode") == "commit"
        ]

        if existing_commit_records:
            existing_commit_records.sort(key=lambda record: record.created_at)
            reported_mode = "dry_run" if mode == "dry_run" else "commit"

            return {
                "plan_id": plan_id,
                "dispatch_mode": reported_mode,
                "plan_execution_status": compute_plan_execution_status(
                    existing_commit_records
                ).value,
                "overall_progress": compute_overall_progress(existing_commit_records),
                "records": [
                    action_execution_record_view(r) for r in existing_commit_records
                ],
                "compensation_hints": [], # Historic records don't have active hints
            }

        summary = self.dispatch_service.dispatch_plan(plan, mode=mode)

        # Persist only commit-mode records; dry-run is preview-only.
        if mode == "commit":
            for record in summary.records:
                self.store.save_action_execution_record(
                    record.execution_id, record.model_dump(mode="json")
                )

        # Mapping to PlanDispatchResponse format
        return {
            "plan_id": summary.plan_id,
            "dispatch_mode": summary.dispatch_mode,
            "plan_execution_status": summary.plan_execution_status.value,
            "overall_progress": summary.overall_progress,
            "records": [action_execution_record_view(r) for r in summary.records],
            "compensation_hints": normalize_display_list(summary.compensation_hints),
        }

    def update_execution_progress(
        self, execution_id: str, percentage: float
    ) -> ActionExecutionRecordView:
        payload = self.store.get_action_execution_record(execution_id)
        if payload is None:
            # Fallback for old/missing records
            record = ActionExecutionRecord(
                execution_id=execution_id,
                plan_id="manual",
                action_id="manual",
                action_type="REORDER",
                target_system="ERP",
                idempotency_key=f"manual_{execution_id}",
            )
        else:
            record = ActionExecutionRecord.model_validate(payload)

        record.set_progress(percentage)
        if percentage >= 100.0:
            record.mark_completed()

        self.store.save_action_execution_record(
            record.execution_id, record.model_dump(mode="json")
        )
        return action_execution_record_view(record)

    def complete_execution(self, execution_id: str) -> ActionExecutionRecordView:
        return self.update_execution_progress(execution_id, 100.0)

    def list_executions(self, limit: int = 20) -> list[ActionExecutionRecordView]:
        records = self.store.list_action_execution_records(limit=limit)
        return [action_execution_record_view(r) for r in records]


def make_runtime(store: SQLiteStore | None = None) -> ControlTowerRuntime:
    return ControlTowerRuntime.create(store=store)


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def service_flags_view() -> ServiceFlagsView:
    settings = load_settings()
    return ServiceFlagsView(
        llm_enabled=settings.enabled,
        llm_provider=settings.provider,
        llm_model=settings.model,
        llm_timeout_s=settings.timeout_s,
        llm_retry_attempts=settings.retry_attempts,
        planner_mode=settings.planner_mode,
        dispatch_mode=settings.dispatch_mode,
    )


def service_metrics_view(runtime: ControlTowerRuntime) -> ServiceMetricsView:
    runs = [
        RunRecord.model_validate(item)
        for item in runtime.store.list_run_records(limit=None)
    ]
    traces = [
        OrchestrationTrace.model_validate(item)
        for item in runtime.store.list_traces(limit=None)
    ]
    executions = [
        ExecutionRecord.model_validate(item)
        for item in runtime.store.list_execution_records(limit=None)
    ]
    total_runs = len(runs)
    completed_runs = sum(1 for item in runs if item.status == RunStatus.COMPLETED)
    failed_runs = sum(1 for item in runs if item.status == RunStatus.FAILED)
    run_durations = [item.duration_ms for item in runs if item.duration_ms > 0.0]
    step_durations = [
        step.duration_ms
        for trace in traces
        for step in trace.steps
        if step.duration_ms is not None and step.duration_ms >= 0.0
    ]
    approval_count = sum(
        1
        for item in runs
        if item.approval_status
        in {
            ApprovalStatus.PENDING.value,
            ApprovalStatus.APPROVED.value,
            ApprovalStatus.REJECTED.value,
        }
    )
    execution_failures = sum(
        1
        for item in executions
        if item.status in {ExecutionStatus.FAILED, ExecutionStatus.ROLLED_BACK}
    )
    return ServiceMetricsView(
        total_runs=total_runs,
        completed_runs=completed_runs,
        failed_runs=failed_runs,
        total_events=len(runtime.store.list_event_envelopes(limit=None)),
        total_executions=len(executions),
        avg_run_duration_ms=_average(run_durations),
        avg_agent_step_duration_ms=_average(step_durations),
        llm_fallback_rate=round(
            sum(1 for item in runs if item.llm_fallback_used) / total_runs,
            4,
        )
        if total_runs
        else 0.0,
        approval_rate=round(approval_count / total_runs, 4) if total_runs else 0.0,
        execution_failure_rate=round(execution_failures / len(executions), 4)
        if executions
        else 0.0,
        latest_run_id=runs[0].run_id if runs else None,
    )


def service_runtime_view(runtime: ControlTowerRuntime) -> ServiceRuntimeView:
    return ServiceRuntimeView(
        flags=service_flags_view(),
        metrics=service_metrics_view(runtime),
    )


def kpi_view(kpis) -> KPIView:
    return KPIView(**kpis.model_dump())


def event_envelope_view(item: EventEnvelope | dict) -> EventEnvelopeView:
    payload = (
        item if isinstance(item, EventEnvelope) else EventEnvelope.model_validate(item)
    )
    return EventEnvelopeView(**payload.model_dump(mode="json"))


def run_record_view(item: RunRecord | dict) -> RunView:
    payload = item if isinstance(item, RunRecord) else RunRecord.model_validate(item)
    return RunView(
        run_id=payload.run_id,
        run_type=payload.run_type,
        parent_run_id=payload.parent_run_id,
        correlation_id=payload.correlation_id,
        trigger_event_id=payload.trigger_event_id,
        input_event_ids=payload.input_event_ids,
        mode_before=payload.mode_before,
        mode_after=payload.mode_after,
        status=payload.status,
        started_at=payload.started_at,
        completed_at=payload.completed_at,
        duration_ms=payload.duration_ms,
        decision_id=payload.decision_id,
        selected_plan_id=payload.selected_plan_id,
        execution_id=payload.execution_id,
        approval_status=payload.approval_status,
        llm_fallback_used=payload.llm_fallback_used,
        llm_fallback_reason=normalize_display_text(payload.llm_fallback_reason),
        selected_plan_summary=(
            SelectedPlanSummaryView(
                plan_id=payload.selected_plan_summary.plan_id,
                strategy_label=payload.selected_plan_summary.strategy_label,
                generated_by=payload.selected_plan_summary.generated_by,
                approval_required=payload.selected_plan_summary.approval_required,
                approval_reason=normalize_display_text(
                    payload.selected_plan_summary.approval_reason
                )
                or "",
                score=payload.selected_plan_summary.score,
                action_ids=payload.selected_plan_summary.action_ids,
            )
            if payload.selected_plan_summary is not None
            else None
        ),
        execution_summary=(
            ExecutionSummaryView(
                status=payload.execution_summary.status,
                dispatch_mode=payload.execution_summary.dispatch_mode,
                action_ids=payload.execution_summary.action_ids,
            )
            if payload.execution_summary is not None
            else None
        ),
    )


def run_record_list_view(items: list[RunRecord | dict]) -> list[RunView]:
    return [run_record_view(item) for item in items]


def execution_record_view(item: ExecutionRecord | dict) -> ExecutionRecordView:
    payload = (
        item
        if isinstance(item, ExecutionRecord)
        else ExecutionRecord.model_validate(item)
    )
    return ExecutionRecordView(
        execution_id=payload.execution_id,
        run_id=payload.run_id,
        decision_id=payload.decision_id,
        plan_id=payload.plan_id,
        status=payload.status,
        dispatch_mode=payload.dispatch_mode,
        dry_run=payload.dry_run,
        target_system=payload.target_system,
        action_ids=payload.action_ids,
        receipts=[
            {
                "receipt_id": receipt.receipt_id,
                "action_id": receipt.action_id,
                "status": receipt.status,
                "detail": normalize_display_text(receipt.detail) or "",
            }
            for receipt in payload.receipts
        ],
        status_history=[
            {
                "status": transition.status,
                "timestamp": transition.timestamp,
                "reason": normalize_display_text(transition.reason) or "",
            }
            for transition in payload.status_history
        ],
        failure_reason=normalize_display_text(payload.failure_reason),
        created_at=payload.created_at,
        updated_at=payload.updated_at,
    )


def action_execution_record_view(
    item: ActionExecutionRecord | dict,
) -> ActionExecutionRecordView:
    payload = (
        item
        if isinstance(item, ActionExecutionRecord)
        else ActionExecutionRecord.model_validate(item)
    )
    return ActionExecutionRecordView(
        execution_id=payload.execution_id,
        plan_id=payload.plan_id,
        dispatch_mode=payload.dispatch_mode,
        action_id=payload.action_id,
        action_type=payload.action_type,
        target_system=payload.target_system,
        payload=payload.payload,
        idempotency_key=payload.idempotency_key,
        status=payload.status,
        receipt=payload.receipt,
        failure_reason=normalize_display_text(payload.failure_reason),
        is_retryable=payload.is_retryable,
        created_at=payload.created_at,
        dispatched_at=payload.dispatched_at,
        applied_at=payload.applied_at,
        estimated_completion_at=payload.estimated_completion_at,
        progress_percentage=payload.progress_percentage,
    )


def historical_control_tower_state(
    state_snapshot: SystemState | dict,
) -> ControlTowerStateResponse:
    state = (
        state_snapshot
        if isinstance(state_snapshot, SystemState)
        else SystemState.model_validate(state_snapshot)
    )
    return control_tower_state(state)


def _decision_for_plan(state: SystemState, plan: Plan | None) -> DecisionLog | None:
    if plan is None:
        return None
    for item in reversed(state.decision_logs):
        if item.plan_id == plan.plan_id:
            return item
    return None


def action_view(action: Action) -> ActionView:
    return ActionView(
        action_id=action.action_id,
        action_type=action.action_type.value,
        target_id=action.target_id,
        reason=normalize_display_text(action.reason) or "",
        priority=action.priority,
        estimated_cost_delta=action.estimated_cost_delta,
        estimated_service_delta=action.estimated_service_delta,
        estimated_risk_delta=action.estimated_risk_delta,
        estimated_recovery_hours=action.estimated_recovery_hours,
        parameters=action.parameters,
    )


def constraint_violation_view(item: ConstraintViolation) -> ConstraintViolationView:
    return ConstraintViolationView(
        code=item.code.value if hasattr(item.code, "value") else item.code,
        message=normalize_display_text(item.message) or "",
        action_id=item.action_id,
        severity=item.severity,
    )


def projection_step_view(item) -> ProjectionStepView:
    return ProjectionStepView(
        step_index=item.step_index,
        label=item.label,
        kpis=kpi_view(item.kpis),
        event_severity=item.event_severity,
        inventory_at_risk=item.inventory_at_risk,
        inventory_out_of_stock=item.inventory_out_of_stock,
        backlog_units=item.backlog_units,
        inbound_units_due=item.inbound_units_due,
        summary=normalize_display_text(item.summary) or "",
        key_changes=normalize_display_list(item.key_changes),
    )


def projected_state_summary_view(item) -> ProjectedStateSummaryView:
    return ProjectedStateSummaryView(
        inventory_at_risk=item.inventory_at_risk,
        inventory_out_of_stock=item.inventory_out_of_stock,
        backlog_units=item.backlog_units,
        inbound_units_scheduled=item.inbound_units_scheduled,
        dominant_constraint=normalize_display_text(item.dominant_constraint) or "",
        event_severity_end=item.event_severity_end,
        summary=normalize_display_text(item.summary) or "",
    )


def plan_view(
    plan: Plan | None, decision: DecisionLog | None = None
) -> PlanView | None:
    if plan is None:
        return None
    return PlanView(
        plan_id=plan.plan_id,
        decision_id=decision.decision_id if decision else None,
        mode=plan.mode.value,
        status=plan.status.value,
        score=plan.score,
        score_breakdown=plan.score_breakdown,
        feasible=plan.feasible,
        violations=[constraint_violation_view(item) for item in plan.violations],
        mode_rationale=normalize_display_text(plan.mode_rationale) or "",
        strategy_label=plan.strategy_label,
        generated_by=plan.generated_by,
        approval_required=plan.approval_required,
        approval_reason=normalize_display_text(plan.approval_reason) or "",
        approval_status=decision.approval_status.value
        if decision
        else ApprovalStatus.NOT_REQUIRED.value,
        planner_reasoning=normalize_display_text(plan.planner_reasoning) or "",
        llm_planner_narrative=normalize_display_text(plan.llm_planner_narrative),
        critic_summary=normalize_display_text(plan.critic_summary),
        trigger_event_ids=plan.trigger_event_ids,
        actions=[action_view(item) for item in plan.actions],
        metadata=(
            normalize_display_payload(plan.metadata.model_dump(mode="json"))
            if plan.metadata
            else {}
        ),
    )


def latest_plan_view(state: SystemState) -> PlanView | None:
    plan = state.pending_plan or state.latest_plan
    return plan_view(plan, _decision_for_plan(state, plan))


def event_view(event: Event) -> EventView:
    return EventView(
        event_id=event.event_id,
        type=event.type.value,
        severity=event.severity,
        source=event.source,
        entity_ids=event.entity_ids,
        occurred_at=event.occurred_at,
        detected_at=event.detected_at,
        payload=event.payload,
    )


def candidate_evaluation_view(item) -> CandidateEvaluationView:
    return CandidateEvaluationView(
        strategy_label=item.strategy_label,
        action_ids=item.action_ids,
        score=item.score,
        score_breakdown=item.score_breakdown,
        projected_kpis=kpi_view(item.projected_kpis),
        worst_case_kpis=kpi_view(item.worst_case_kpis)
        if item.worst_case_kpis is not None
        else None,
        simulation_horizon_days=item.simulation_horizon_days,
        projection_steps=[projection_step_view(step) for step in item.projection_steps],
        projected_state_summary=(
            projected_state_summary_view(item.projected_state_summary)
            if item.projected_state_summary is not None
            else None
        ),
        projection_summary=normalize_display_text(item.projection_summary) or "",
        feasible=item.feasible,
        violations=[
            constraint_violation_view(violation) for violation in item.violations
        ],
        mode_rationale=normalize_display_text(item.mode_rationale) or "",
        approval_required=item.approval_required,
        approval_reason=normalize_display_text(item.approval_reason) or "",
        rationale=normalize_display_text(item.rationale) or "",
        llm_used=item.llm_used,
        coverage_fraction=item.coverage_fraction,
        critical_covered=item.critical_covered,
        unresolved_critical=item.unresolved_critical,
    )


def decision_summary_view(item: DecisionLog) -> DecisionLogSummaryView:
    return DecisionLogSummaryView(
        decision_id=item.decision_id,
        plan_id=item.plan_id,
        approval_status=item.approval_status.value,
        approval_required=item.approval_required,
        approval_reason=normalize_display_text(item.approval_reason) or "",
        selection_reason=normalize_display_text(item.selection_reason) or "",
        selected_actions=item.selected_actions,
        event_ids=item.event_ids,
        llm_used=item.llm_used,
    )


def decision_detail_view(item: DecisionLog) -> DecisionLogDetailView:
    return DecisionLogDetailView(
        decision_id=item.decision_id,
        plan_id=item.plan_id,
        approval_status=item.approval_status.value,
        approval_required=item.approval_required,
        approval_reason=normalize_display_text(item.approval_reason) or "",
        rationale=normalize_display_text(item.rationale) or "",
        selection_reason=normalize_display_text(item.selection_reason) or "",
        mode_rationale=normalize_display_text(item.mode_rationale) or "",
        winning_factors=normalize_display_list(item.winning_factors),
        score_breakdown=item.score_breakdown,
        selected_actions=item.selected_actions,
        rejected_actions=normalize_display_payload(item.rejected_actions),
        candidate_evaluations=[
            candidate_evaluation_view(eval_item)
            for eval_item in item.candidate_evaluations
        ],
        critic_summary=normalize_display_text(item.critic_summary),
        critic_findings=normalize_display_list(item.critic_findings),
        llm_used=item.llm_used,
        llm_provider=item.llm_provider,
        llm_model=item.llm_model,
        llm_error=normalize_display_text(item.llm_error),
        before_kpis=kpi_view(item.before_kpis),
        after_kpis=kpi_view(item.after_kpis),
    )


def _approximate_z_score(service_level: float) -> float:
    # Acklam-style approximation is sufficient for deterministic policy scoring.
    p = max(0.5001, min(0.9999, service_level))
    t = math.sqrt(-2.0 * math.log(1.0 - p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    z = t - ((c2 * t + c1) * t + c0) / (((d3 * t + d2) * t + d1) * t + 1.0)
    return max(0.0, z)


def _supplier_for_item(state: SystemState, item) -> Any | None:
    return state.suppliers.get(f"{item.preferred_supplier_id}_{item.sku}")


def _route_factor(state: SystemState, item) -> float:
    route = state.routes.get(item.preferred_route_id)
    if route is None:
        return 1.0
    if route.status == "blocked":
        return 0.0
    # High-risk lanes reduce expected usable inbound, but avoid over-penalizing
    # because route/supplier uncertainty is already reflected in safety stock.
    return max(0.85, 1.0 - (route.risk_score * 0.15))


def _lead_time_days(state: SystemState, item) -> int:
    supplier = _supplier_for_item(state, item)
    return max(int(supplier.lead_time_days), 1) if supplier is not None else 1


def _expected_inbound_within_lt(state: SystemState, item) -> float:
    return max(item.incoming_qty * _route_factor(state, item), 0.0)


def _committed_qty_within_lt(state: SystemState, item) -> int:
    lead_time = _lead_time_days(state, item)
    committed = sum(
        order.quantity
        for order in state.orders
        if order.sku == item.sku and order.day_index <= lead_time
    )
    # Prevent double-counting with forecast-based lead-time demand.
    return min(committed, max(item.forecast_qty, 0))


def _inventory_position(state: SystemState, item) -> float:
    return (
        item.on_hand
        + _expected_inbound_within_lt(state, item)
        - _committed_qty_within_lt(state, item)
    )


def _dynamic_safety_stock(state: SystemState, item) -> float:
    supplier = _supplier_for_item(state, item)
    reliability = supplier.reliability if supplier is not None else 0.9
    lead_time = _lead_time_days(state, item)
    demand_std = max(float(getattr(item, "std_demand", 0.0)), 0.0)
    demand_mean = max(float(item.forecast_qty), 0.0)
    lead_time_std = max((1.0 - reliability) * lead_time, 0.0)
    service_target = 0.95 if reliability >= 0.85 else 0.97
    z = _approximate_z_score(service_target)
    variance = (demand_std**2 * lead_time) + ((demand_mean**2) * (lead_time_std**2))
    dynamic_ss = z * (variance**0.5)
    return max(float(item.safety_stock), dynamic_ss)


def _dynamic_reorder_point(state: SystemState, item) -> float:
    lead_time = _lead_time_days(state, item)
    lead_time_demand = max(float(item.forecast_qty), 0.0) * lead_time
    return lead_time_demand + _dynamic_safety_stock(state, item)


def _inventory_status(state: SystemState, item) -> str:
    inventory_position = _inventory_position(state, item)
    dynamic_ss = _dynamic_safety_stock(state, item)
    dynamic_rop = _dynamic_reorder_point(state, item)
    net_available = item.on_hand - _committed_qty_within_lt(state, item)

    if net_available <= 0 and inventory_position <= 0:
        return "out_of_stock"
    if inventory_position <= dynamic_ss:
        return "at_risk"
    # Small guard-band prevents borderline rounding noise from flooding low alerts.
    if inventory_position <= (dynamic_rop * 0.97):
        return "low"
    return "in_stock"


def inventory_rows(
    state: SystemState, *, search: str | None = None, status: str | None = None
) -> list[InventoryRowView]:
    needle = (search or "").strip().lower()
    status_filter = (status or "").strip().lower()
    rows: list[InventoryRowView] = []
    for item in state.inventory.values():
        item_status = _inventory_status(state, item)
        matches_needle = (
            not needle
            or needle in item.sku.lower()
            or needle in item.preferred_supplier_id.lower()
            or needle in item.name.lower()
        )
        if not matches_needle:
            continue
        if status_filter and item_status != status_filter:
            continue
        rows.append(
            InventoryRowView(
                sku=item.sku,
                name=item.name,
                warehouse_id=item.warehouse_id,
                on_hand=item.on_hand,
                incoming_qty=item.incoming_qty,
                forecast_qty=item.forecast_qty,
                reorder_point=item.reorder_point,
                safety_stock=item.safety_stock,
                unit_cost=item.unit_cost,
                status=item_status,
                preferred_supplier_id=item.preferred_supplier_id,
                preferred_route_id=item.preferred_route_id,
            )
        )
    rows.sort(key=lambda row: (row.status, row.sku))
    return rows


def _supplier_tradeoff(state: SystemState, supplier_id: str, sku: str) -> str:
    current = state.suppliers.get(f"{supplier_id}_{sku}")
    if current is None:
        current = state.suppliers.get(supplier_id)
    if current is None:
        return "unknown"
    peers = [item for item in state.suppliers.values() if item.sku == sku]
    if not peers:
        return "no comparison available"
    fastest = min(peer.lead_time_days for peer in peers)
    cheapest = min(peer.unit_cost for peer in peers)
    if current.lead_time_days == fastest and current.unit_cost > cheapest:
        return "fast but expensive"
    if current.unit_cost == cheapest and current.lead_time_days > fastest:
        return "cheap but slower"
    return "balanced option"


def supplier_rows(
    state: SystemState, *, sku: str | None = None, status: str | None = None
) -> list[SupplierRowView]:
    target_sku = (sku or "").strip().lower()
    target_status = (status or "").strip().lower()
    items: list[SupplierRowView] = []
    for supplier in state.suppliers.values():
        if target_sku and supplier.sku.lower() != target_sku:
            continue
        if target_status and supplier.status.lower() != target_status:
            continue
        items.append(
            SupplierRowView(
                supplier_id=supplier.supplier_id,
                sku=supplier.sku,
                unit_cost=supplier.unit_cost,
                lead_time_days=supplier.lead_time_days,
                reliability=supplier.reliability,
                is_primary=supplier.is_primary,
                status=supplier.status,
                tradeoff=normalize_display_text(
                    _supplier_tradeoff(state, supplier.supplier_id, supplier.sku)
                )
                or "",
            )
        )
    items.sort(key=lambda row: (row.sku, -row.reliability, row.lead_time_days))
    return items


def alerts(state: SystemState) -> list[AlertView]:
    items: list[AlertView] = []
    for event in state.active_events:
        level = "critical" if event.severity >= 0.8 else "warning"
        items.append(
            AlertView(
                level=level,
                title=event.type.value.replace("_", " ").title(),
                message=normalize_display_text(
                    f"Detected from {event.source} with severity {event.severity:.2f}"
                )
                or "",
                source="event",
                event_type=event.type.value,
                entity_ids=event.entity_ids,
            )
        )
    for row in inventory_rows(state):
        if row.status not in {"low", "out_of_stock"}:
            continue
        items.append(
            AlertView(
                level="critical" if row.status == "out_of_stock" else "warning",
                title=f"{row.sku} inventory {row.status.replace('_', ' ')}",
                message=normalize_display_text(
                    f"On hand {row.on_hand}, incoming {row.incoming_qty}, reorder point {row.reorder_point}"
                )
                or "",
                source="inventory",
                entity_ids=[row.sku],
            )
        )
        if len(items) >= 6:
            break
    return items[:6]


def pending_approval_view(state: SystemState) -> PendingApprovalView | None:
    if state.pending_plan is None or not state.decision_logs:
        return None
    decision = state.decision_logs[-1]
    can_request_safer = state.pending_plan.generated_by != "operator_safer_request"
    allowed_actions = ["approve", "reject"] + (
        ["safer_plan"] if can_request_safer else []
    )
    return PendingApprovalView(
        decision_id=decision.decision_id,
        approval_status=decision.approval_status.value,
        approval_reason=normalize_display_text(decision.approval_reason) or "",
        selection_reason=normalize_display_text(decision.selection_reason) or "",
        selected_actions=decision.selected_actions,
        allowed_actions=allowed_actions,
        before_kpis=kpi_view(decision.before_kpis),
        projected_kpis=kpi_view(decision.after_kpis),
        candidate_count=len(decision.candidate_evaluations),
        plan=plan_view(state.pending_plan, decision),
    )


def approval_detail_view(state: SystemState, decision_id: str) -> ApprovalDetailView:
    decision = find_decision(state, decision_id)
    plan = (
        state.pending_plan
        if state.pending_plan and state.pending_plan.plan_id == decision.plan_id
        else state.latest_plan
    )
    if plan is None or plan.plan_id != decision.plan_id:
        plan = None
    pending = (
        state.pending_plan is not None
        and state.pending_plan.plan_id == decision.plan_id
    )
    can_request_safer = (
        not pending or state.pending_plan.generated_by != "operator_safer_request"
    )
    allowed_actions = ["approve", "reject"] + (
        ["safer_plan"] if can_request_safer else []
    )
    return ApprovalDetailView(
        decision_id=decision.decision_id,
        plan_id=decision.plan_id,
        approval_required=decision.approval_required,
        approval_status=decision.approval_status.value,
        approval_reason=normalize_display_text(decision.approval_reason) or "",
        is_pending=pending,
        allowed_actions=allowed_actions if pending else [],
        selection_reason=normalize_display_text(decision.selection_reason) or "",
        selected_actions=decision.selected_actions,
        event_ids=decision.event_ids,
        before_kpis=kpi_view(decision.before_kpis),
        after_kpis=kpi_view(decision.after_kpis),
        candidate_count=len(decision.candidate_evaluations),
        plan=plan_view(plan, decision)
        if plan is not None
        else PlanView(
            plan_id=decision.plan_id,
            decision_id=decision.decision_id,
            mode=state.mode.value,
            status="unknown",
            score=0.0,
            score_breakdown=decision.score_breakdown,
            approval_required=decision.approval_required,
            approval_reason=normalize_display_text(decision.approval_reason) or "",
            approval_status=decision.approval_status.value,
        ),
    )


def approval_command_result_view(
    state: SystemState,
    *,
    decision_id: str,
    action: str,
    execution: ExecutionRecord | None = None,
) -> ApprovalCommandResultResponse:
    message_map = {
        "approve": "Pending plan approved and queued for dispatch.",
        "reject": "Pending plan rejected.",
        "safer_plan": "Safer plan requested.",
        "select_alternative": "Alternative strategy selected and queued for approval.",
    }
    decision = find_decision(state, decision_id)
    return ApprovalCommandResultResponse(
        decision_id=decision.decision_id,
        action=action,
        approval_status=decision.approval_status.value,
        message=normalize_display_text(
            message_map.get(action, "Approval action processed.")
        )
        or "",
        latest_plan=latest_plan_view(state),
        pending_approval=pending_approval_view(state),
        execution=execution_record_view(execution) if execution is not None else None,
        latest_trace=latest_trace_view(state),
        summary=control_tower_summary(state),
    )


def latest_trace_view(state: SystemState) -> TraceView:
    trace = state.latest_trace
    latest_decision = state.decision_logs[-1] if state.decision_logs else None
    latest_event = state.active_events[-1] if state.active_events else None
    if trace is None:
        return TraceView(
            run_id=state.run_id,
            mode=state.mode.value,
            current_branch=state.mode.value,
            event=event_view(latest_event) if latest_event else None,
            latest_plan=latest_plan_view(state),
            decision_id=latest_decision.decision_id if latest_decision else None,
            selected_strategy=state.latest_plan.strategy_label
            if state.latest_plan
            else None,
            candidate_count=len(latest_decision.candidate_evaluations)
            if latest_decision
            else 0,
            selection_reason=normalize_display_text(latest_decision.selection_reason)
            if latest_decision
            else None,
            candidate_evaluations=(
                [
                    candidate_evaluation_view(item)
                    for item in latest_decision.candidate_evaluations
                ]
                if latest_decision
                else []
            ),
            approval_pending=state.pending_plan is not None,
            approval_reason=(
                normalize_display_text(latest_decision.approval_reason) or ""
                if latest_decision
                else ""
            ),
            critic_summary=(
                normalize_display_text(latest_decision.critic_summary)
                if latest_decision
                else None
            ),
        )

    steps = [
        AgentStepView(
            step_id=step.step_id,
            sequence=step.sequence,
            agent=step.node_key,
            node_type=step.node_type,
            status=step.status,
            started_at=step.started_at,
            completed_at=step.completed_at,
            duration_ms=step.duration_ms,
            mode_snapshot=step.mode_snapshot,
            summary=normalize_display_text(step.summary) or "",
            reasoning_source=step.reasoning_source,
            input_snapshot=step.input_snapshot,
            output_snapshot=normalize_display_payload(step.output_snapshot),
            observations=normalize_display_list(step.observations),
            risks=normalize_display_list(step.risks),
            downstream_impacts=normalize_display_list(step.downstream_impacts),
            recommended_action_ids=step.recommended_action_ids,
            tradeoffs=normalize_display_list(step.tradeoffs),
            llm_used=step.llm_used,
            llm_error=normalize_display_text(step.llm_error),
            fallback_used=step.fallback_used,
            fallback_reason=normalize_display_text(step.fallback_reason),
        )
        for step in trace.steps
    ]
    return TraceView(
        run_id=trace.run_id,
        trace_id=trace.trace_id,
        status=trace.status,
        started_at=trace.started_at,
        completed_at=trace.completed_at,
        mode_before=trace.mode_before,
        mode_after=trace.mode_after,
        mode=state.mode.value,
        current_branch=trace.current_branch,
        terminal_stage=trace.terminal_stage,
        event=event_view(trace.event)
        if trace.event
        else event_view(latest_event)
        if latest_event
        else None,
        route_decisions=[
            RouteDecisionView(
                from_node=item.from_node,
                outcome=item.outcome,
                to_node=item.to_node,
                reason=normalize_display_text(item.reason) or "",
            )
            for item in trace.route_decisions
        ],
        steps=steps,
        latest_plan=latest_plan_view(state),
        decision_id=trace.decision_id or latest_decision.decision_id
        if latest_decision
        else trace.decision_id,
        selected_strategy=trace.selected_strategy
        or (state.latest_plan.strategy_label if state.latest_plan else None),
        candidate_count=trace.candidate_count,
        selection_reason=normalize_display_text(
            trace.selection_reason
            or (latest_decision.selection_reason if latest_decision else None)
        ),
        candidate_evaluations=(
            [
                candidate_evaluation_view(item)
                for item in latest_decision.candidate_evaluations
            ]
            if latest_decision
            else []
        ),
        approval_pending=trace.approval_pending,
        approval_reason=normalize_display_text(trace.approval_reason) or "",
        execution_status=trace.execution_status,
        critic_summary=normalize_display_text(
            trace.critic_summary
            or (latest_decision.critic_summary if latest_decision else None)
        ),
    )


def trace_view_from_record(
    trace: OrchestrationTrace, run: RunRecord | None = None
) -> TraceView:
    steps = [
        AgentStepView(
            step_id=step.step_id,
            sequence=step.sequence,
            agent=step.node_key,
            node_type=step.node_type,
            status=step.status,
            started_at=step.started_at,
            completed_at=step.completed_at,
            duration_ms=step.duration_ms,
            mode_snapshot=step.mode_snapshot,
            summary=normalize_display_text(step.summary) or "",
            reasoning_source=step.reasoning_source,
            input_snapshot=step.input_snapshot,
            output_snapshot=normalize_display_payload(step.output_snapshot),
            observations=normalize_display_list(step.observations),
            risks=normalize_display_list(step.risks),
            downstream_impacts=normalize_display_list(step.downstream_impacts),
            recommended_action_ids=step.recommended_action_ids,
            tradeoffs=normalize_display_list(step.tradeoffs),
            llm_used=step.llm_used,
            llm_error=normalize_display_text(step.llm_error),
            fallback_used=step.fallback_used,
            fallback_reason=normalize_display_text(step.fallback_reason),
        )
        for step in trace.steps
    ]
    return TraceView(
        run_id=trace.run_id,
        trace_id=trace.trace_id,
        status=trace.status,
        started_at=trace.started_at,
        completed_at=trace.completed_at,
        mode_before=trace.mode_before,
        mode_after=trace.mode_after,
        mode=trace.mode_after or trace.mode_before,
        current_branch=trace.current_branch,
        terminal_stage=trace.terminal_stage,
        event=event_view(trace.event) if trace.event else None,
        route_decisions=[
            RouteDecisionView(
                from_node=item.from_node,
                outcome=item.outcome,
                to_node=item.to_node,
                reason=normalize_display_text(item.reason) or "",
            )
            for item in trace.route_decisions
        ],
        steps=steps,
        latest_plan=None,
        decision_id=run.decision_id if run else trace.decision_id,
        selected_strategy=trace.selected_strategy
        or (
            run.selected_plan_summary.strategy_label
            if run and run.selected_plan_summary
            else None
        ),
        candidate_count=trace.candidate_count,
        selection_reason=normalize_display_text(trace.selection_reason),
        candidate_evaluations=[],
        approval_pending=trace.approval_pending,
        approval_reason=normalize_display_text(trace.approval_reason) or "",
        execution_status=trace.execution_status,
        critic_summary=normalize_display_text(trace.critic_summary),
    )


def reflection_views(state: SystemState) -> list[ReflectionView]:
    if state.memory is None:
        return []
    items = [
        ReflectionView(
            note_id=item.note_id,
            run_id=item.run_id,
            scenario_id=item.scenario_id,
            plan_id=item.plan_id,
            mode=item.mode,
            approval_status=item.approval_status,
            summary=normalize_display_text(item.summary) or "",
            lessons=normalize_display_list(item.lessons),
            pattern_tags=item.pattern_tags,
            follow_up_checks=normalize_display_list(item.follow_up_checks),
            llm_used=item.llm_used,
            llm_error=normalize_display_text(item.llm_error),
        )
        for item in state.memory.reflection_notes
    ]
    return list(reversed(items))


def scenario_outcomes(state: SystemState) -> list[ScenarioOutcomeView]:
    if state.memory is None:
        return []
    items: list[ScenarioOutcomeView] = []
    for scenario_id, payload in sorted(state.memory.scenario_outcomes.items()):
        items.append(
            ScenarioOutcomeView(
                scenario_id=scenario_id,
                runs=int(payload.get("runs", 0)),
                latest_run_id=payload.get("latest_run_id"),
                latest_plan_id=payload.get("latest_plan_id"),
                latest_approval_status=payload.get("latest_approval_status"),
                latest_reflection_status=payload.get("latest_reflection_status"),
                latest_kpis=payload.get("latest_kpis", {}),
                history=payload.get("history", []),
            )
        )
    return items


def control_tower_summary(state: SystemState) -> ControlTowerSummaryResponse:
    if state.kpis.decision_latency_ms < 0.0:
        state.kpis = recompute_kpis(state)
    return ControlTowerSummaryResponse(
        mode=state.mode.value,
        kpis=kpi_view(state.kpis),
        alerts=alerts(state),
        active_events=[event_view(event) for event in state.active_events],
        latest_plan=latest_plan_view(state),
        pending_approval=pending_approval_view(state),
        decision_count=len(state.decision_logs),
        scenario_history_count=len(state.scenario_history),
    )


def control_tower_state(state: SystemState) -> ControlTowerStateResponse:
    return ControlTowerStateResponse(
        summary=control_tower_summary(state),
        inventory=inventory_rows(state),
        suppliers=supplier_rows(state),
        reflections=reflection_views(state),
        latest_trace=latest_trace_view(state),
    )


def find_decision(state: SystemState, decision_id: str) -> DecisionLog:
    for item in reversed(state.decision_logs):
        if item.decision_id == decision_id:
            return item
    raise_not_found("decision", decision_id)


def build_event_from_request(
    *,
    event_type,
    severity: float,
    source: str,
    entity_ids: list[str],
    payload: dict[str, Any],
) -> Event:
    timestamp = utc_now()
    return Event(
        event_id=f"evt_api_{event_type.value}_{int(timestamp.timestamp())}",
        type=event_type,
        source=source,
        severity=severity,
        entity_ids=entity_ids,
        occurred_at=timestamp,
        detected_at=timestamp,
        payload=payload,
        dedupe_key=f"{event_type.value}:{entity_ids}:{payload}",
    )


def build_event_from_envelope(envelope: EventEnvelope) -> Event:
    try:
        event_type = EventType(envelope.event_type)
    except ValueError as exc:
        raise ValueError(
            f"unsupported domain event type: {envelope.event_type}"
        ) from exc
    return Event(
        event_id=envelope.event_id,
        type=event_type,
        source=envelope.source,
        severity=envelope.severity,
        entity_ids=envelope.entity_ids,
        occurred_at=envelope.occurred_at,
        detected_at=envelope.ingested_at,
        payload=envelope.payload,
        dedupe_key=envelope.idempotency_key,
    )




