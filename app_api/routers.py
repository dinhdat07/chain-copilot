from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from app_api.schemas import (
    ApprovalCommandResultResponse,
    ApprovalDetailResponse,
    ApprovalCommandRequest,
    ControlTowerStateResponse,
    ControlTowerSummaryResponse,
    DecisionLogDetailResponse,
    DecisionLogListResponse,
    DispatchModeRequest,
    EventIngestRequest,
    EventIngestResponse,
    EventListResponse,
    EventRequest,
    ExecutionDetailResponse,
    ErrorResponse,
    InventoryListResponse,
    LegacyApprovalRequest,
    PendingApprovalResponse,
    PlanDetailResponse,
    ProgressRequest,
    ReflectionListResponse,
    RunDetailResponse,
    RunListResponse,
    RunStateResponse,
    ScenarioRequest,
    ServiceRuntimeResponse,
    SupplierListResponse,
    TraceResponse,
    WhatIfRequest,
)
from app_api.services import (
    approval_command_result_view,
    approval_detail_view,
    ControlTowerRuntime,
    build_event_from_request,
    control_tower_state,
    control_tower_summary,
    decision_detail_view,
    decision_summary_view,
    event_envelope_view,
    execution_record_view,
    inventory_rows,
    latest_trace_view,
    pending_approval_view,
    plan_view,
    raise_not_found,
    reflection_views,
    run_record_view,
    run_record_list_view,
    scenario_outcomes,
    service_runtime_view,
    supplier_rows,
    trace_view_from_record,
    historical_control_tower_state,
)
from core.models import DecisionLog, OrchestrationTrace
from core.runtime_records import RunRecord


def create_router(runtime_getter: Callable[[], ControlTowerRuntime]) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1",
        responses={
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )

    @router.get("/control-tower/summary", response_model=ControlTowerSummaryResponse)
    def get_control_tower_summary() -> ControlTowerSummaryResponse:
        runtime = runtime_getter()
        return control_tower_summary(runtime.state)

    @router.get("/control-tower/state", response_model=ControlTowerStateResponse)
    def get_control_tower_state() -> ControlTowerStateResponse:
        runtime = runtime_getter()
        return control_tower_state(runtime.state)

    @router.get("/service/runtime", response_model=ServiceRuntimeResponse)
    def get_service_runtime() -> ServiceRuntimeResponse:
        runtime = runtime_getter()
        return ServiceRuntimeResponse(item=service_runtime_view(runtime))

    @router.get("/inventory", response_model=InventoryListResponse)
    def get_inventory(search: str | None = None, status: str | None = None) -> InventoryListResponse:
        runtime = runtime_getter()
        items = inventory_rows(runtime.state, search=search, status=status)
        return InventoryListResponse(items=items, total=len(items))

    @router.get("/suppliers", response_model=SupplierListResponse)
    def get_suppliers(sku: str | None = None, status: str | None = None) -> SupplierListResponse:
        runtime = runtime_getter()
        items = supplier_rows(runtime.state, sku=sku, status=status)
        return SupplierListResponse(items=items, total=len(items))

    @router.get("/events", response_model=EventListResponse)
    def get_events(limit: int = 20) -> EventListResponse:
        runtime = runtime_getter()
        items = [item.model_copy(deep=True) for item in control_tower_summary(runtime.state).active_events[:max(limit, 0)]]
        return EventListResponse(items=items, total=len(runtime.state.active_events))

    @router.get("/plans/latest", response_model=PlanDetailResponse)
    def get_latest_plan() -> PlanDetailResponse:
        runtime = runtime_getter()
        return PlanDetailResponse(item=plan_view(runtime.state.pending_plan or runtime.state.latest_plan))

    @router.get("/approvals/pending", response_model=PendingApprovalResponse)
    def get_pending_approval() -> PendingApprovalResponse:
        runtime = runtime_getter()
        return PendingApprovalResponse(item=pending_approval_view(runtime.state))

    @router.get("/approvals/{decision_id}", response_model=ApprovalDetailResponse)
    def get_approval(decision_id: str) -> ApprovalDetailResponse:
        runtime = runtime_getter()
        return ApprovalDetailResponse(item=approval_detail_view(runtime.state, decision_id))

    @router.post("/approvals/{decision_id}", response_model=ApprovalCommandResultResponse)
    def approval_command(decision_id: str, request: ApprovalCommandRequest) -> ApprovalCommandResultResponse:
        runtime = runtime_getter()
        runtime.approval_command(decision_id, request.action)
        resolved_decision_id = runtime.current_decision_id() or decision_id
        return approval_command_result_view(
            runtime.state,
            decision_id=resolved_decision_id,
            action=request.action,
            execution=runtime.latest_execution(),
        )

    @router.get("/decision-logs", response_model=DecisionLogListResponse)
    def get_decision_logs() -> DecisionLogListResponse:
        runtime = runtime_getter()
        return DecisionLogListResponse(
            items=[
                decision_summary_view(DecisionLog.model_validate(item))
                for item in runtime.store.list_decision_logs()
            ]
        )

    @router.get("/decision-logs/{decision_id}", response_model=DecisionLogDetailResponse)
    def get_decision_log_detail(decision_id: str) -> DecisionLogDetailResponse:
        runtime = runtime_getter()
        payload = runtime.store.get_decision_log(decision_id)
        if payload is None:
            raise_not_found("decision", decision_id)
        return DecisionLogDetailResponse(item=decision_detail_view(DecisionLog.model_validate(payload)))

    @router.get("/trace/latest", response_model=TraceResponse)
    def get_latest_trace() -> TraceResponse:
        runtime = runtime_getter()
        return TraceResponse(item=latest_trace_view(runtime.state))

    @router.get("/reflections", response_model=ReflectionListResponse)
    def get_reflections() -> ReflectionListResponse:
        runtime = runtime_getter()
        memory = runtime.state.memory
        return ReflectionListResponse(
            items=reflection_views(runtime.state),
            scenarios=scenario_outcomes(runtime.state),
            pattern_tag_counts={} if memory is None else memory.pattern_tag_counts,
        )

    @router.get("/state")
    def get_state() -> dict:
        runtime = runtime_getter()
        return {"summary": control_tower_summary(runtime.state).model_dump(mode="json"), "state": runtime.state.model_dump(mode="json")}

    @router.post("/reset")
    def reset_state() -> dict:
        runtime = runtime_getter()
        runtime.reset()
        return {"summary": control_tower_summary(runtime.state).model_dump(mode="json"), "state": runtime.state.model_dump(mode="json")}

    @router.post("/plan/daily")
    def daily_plan() -> dict:
        runtime = runtime_getter()
        try:
            runtime.run_daily()
        except HTTPException as exc:
            if exc.status_code == 409 and isinstance(exc.detail, dict):
                raise HTTPException(status_code=409, detail=exc.detail["message"]) from exc
            raise
        return runtime.legacy_response_payload()

    @router.post("/events")
    def ingest_event(request: EventRequest) -> dict:
        runtime = runtime_getter()
        event = build_event_from_request(
            event_type=request.type,
            severity=request.severity,
            source=request.source,
            entity_ids=request.entity_ids,
            payload=request.payload,
        )
        runtime.ingest_event(event)
        return runtime.legacy_response_payload()

    @router.post("/events/ingest", response_model=EventIngestResponse)
    def ingest_envelope(request: EventIngestRequest) -> EventIngestResponse:
        runtime = runtime_getter()
        envelope, run_record, execution = runtime.ingest_envelope(request)
        return EventIngestResponse(
            event=event_envelope_view(envelope),
            accepted=True,
            run_id=None if run_record is None else run_record.run_id,
            execution_id=None if execution is None else execution.execution_id,
        )

    @router.get("/runs/{run_id}", response_model=RunDetailResponse)
    def get_run(run_id: str) -> RunDetailResponse:
        runtime = runtime_getter()
        payload = runtime.store.get_run_record(run_id)
        if payload is None:
            raise_not_found("run", run_id)
        return RunDetailResponse(item=run_record_view(payload))

    @router.get("/runs", response_model=RunListResponse)
    def list_runs(limit: int = 20) -> RunListResponse:
        runtime = runtime_getter()
        items = runtime.store.list_run_records(limit=max(limit, 0))
        return RunListResponse(
            items=run_record_list_view(items),
            total=len(runtime.store.list_run_records(limit=None)),
        )

    @router.get("/runs/{run_id}/trace", response_model=TraceResponse)
    def get_run_trace(run_id: str) -> TraceResponse:
        runtime = runtime_getter()
        trace_payload = runtime.store.get_trace(run_id)
        if trace_payload is None:
            raise_not_found("trace", run_id)
        run_payload = runtime.store.get_run_record(run_id)
        trace = OrchestrationTrace.model_validate(trace_payload)
        run = RunRecord.model_validate(run_payload) if run_payload is not None else None
        return TraceResponse(item=trace_view_from_record(trace, run=run))

    @router.get("/runs/{run_id}/state", response_model=RunStateResponse)
    def get_run_state(run_id: str) -> RunStateResponse:
        runtime = runtime_getter()
        run_payload = runtime.store.get_run_record(run_id)
        if run_payload is None:
            raise_not_found("run", run_id)
        state_payload = runtime.store.get_state_snapshot(run_id)
        if state_payload is None:
            raise_not_found("state_snapshot", run_id)
        return RunStateResponse(
            run=run_record_view(run_payload),
            state=historical_control_tower_state(state_payload),
        )

    @router.get("/execution/{execution_id}", response_model=ExecutionDetailResponse)
    def get_execution(execution_id: str) -> ExecutionDetailResponse:
        runtime = runtime_getter()
        payload = runtime.store.get_execution_record(execution_id)
        if payload is None:
            raise_not_found("execution", execution_id)
        return ExecutionDetailResponse(item=execution_record_view(payload))

    @router.post("/execution/{plan_id}/dispatch")
    def dispatch_plan(plan_id: str, request: DispatchModeRequest) -> dict:
        runtime = runtime_getter()
        return runtime.dispatch_plan(plan_id, request.mode)

    @router.post("/execution/{execution_id}/progress", response_model=ExecutionDetailResponse)
    def update_execution_progress(execution_id: str, request: ProgressRequest) -> ExecutionDetailResponse:
        runtime = runtime_getter()
        return ExecutionDetailResponse(item=runtime.update_execution_progress(execution_id, request.percentage))

    @router.post("/execution/{execution_id}/complete", response_model=ExecutionDetailResponse)
    def complete_execution(execution_id: str) -> ExecutionDetailResponse:
        runtime = runtime_getter()
        return ExecutionDetailResponse(item=runtime.complete_execution(execution_id))

    @router.post("/scenarios/run")
    def run_scenario(request: ScenarioRequest) -> dict:
        runtime = runtime_getter()
        try:
            runtime.run_scenario(request.scenario_name, seed=request.seed)
        except HTTPException as exc:
            if exc.status_code == 409 and isinstance(exc.detail, dict):
                raise HTTPException(status_code=409, detail=exc.detail["message"]) from exc
            raise
        payload = runtime.legacy_response_payload()
        payload["scenario_history_count"] = len(runtime.state.scenario_history)
        return payload

    @router.post("/decisions/{decision_id}/approve")
    def approve_decision(decision_id: str, request: LegacyApprovalRequest) -> dict:
        runtime = runtime_getter()
        runtime.approval_command(decision_id, "approve" if request.approve else "reject")
        payload = runtime.legacy_response_payload()
        payload["approved"] = request.approve
        return payload

    @router.post("/decisions/{decision_id}/safer-plan")
    def safer_plan(decision_id: str) -> dict:
        runtime = runtime_getter()
        runtime.approval_command(decision_id, "safer_plan")
        return runtime.legacy_response_payload()

    @router.post("/what-if")
    def what_if(request: WhatIfRequest) -> dict:
        runtime = runtime_getter()
        return runtime.what_if(request.scenario_name, seed=request.seed)

    return router
