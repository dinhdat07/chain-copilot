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
    EventListResponse,
    EventRequest,
    InventoryListResponse,
    LegacyApprovalRequest,
    PendingApprovalResponse,
    PlanDetailResponse,
    ReflectionListResponse,
    ScenarioRequest,
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
    find_decision,
    inventory_rows,
    latest_trace_view,
    pending_approval_view,
    plan_view,
    reflection_views,
    scenario_outcomes,
    supplier_rows,
)


def create_router(runtime_getter: Callable[[], ControlTowerRuntime]) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/control-tower/summary", response_model=ControlTowerSummaryResponse)
    def get_control_tower_summary() -> ControlTowerSummaryResponse:
        runtime = runtime_getter()
        return control_tower_summary(runtime.state)

    @router.get("/control-tower/state", response_model=ControlTowerStateResponse)
    def get_control_tower_state() -> ControlTowerStateResponse:
        runtime = runtime_getter()
        return control_tower_state(runtime.state)

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
        return approval_command_result_view(runtime.state, decision_id=resolved_decision_id, action=request.action)

    @router.get("/decision-logs", response_model=DecisionLogListResponse)
    def get_decision_logs() -> DecisionLogListResponse:
        runtime = runtime_getter()
        return DecisionLogListResponse(
            items=[decision_summary_view(item) for item in reversed(runtime.state.decision_logs)]
        )

    @router.get("/decision-logs/{decision_id}", response_model=DecisionLogDetailResponse)
    def get_decision_log_detail(decision_id: str) -> DecisionLogDetailResponse:
        runtime = runtime_getter()
        return DecisionLogDetailResponse(item=decision_detail_view(find_decision(runtime.state, decision_id)))

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
