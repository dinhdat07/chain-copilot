from __future__ import annotations

import asyncio
from collections.abc import Callable

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)

from app_api.schemas import (
    ActionExecutionRecordView,
    ApprovalAlternativeRequest,
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
    ExecutionListResponse,
    ErrorResponse,
    InventoryListResponse,
    LegacyApprovalRequest,
    PendingApprovalResponse,
    PlanDetailResponse,
    PlanDispatchResponse,
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
    action_execution_record_view,
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


MOCK_ENVIRONMENT = "normal"


def create_router(runtime_getter: Callable[[], ControlTowerRuntime]) -> APIRouter:
    router = APIRouter(
        responses={
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )

    @router.get("/mock/weather")
    def mock_weather() -> dict:
        global MOCK_ENVIRONMENT
        if MOCK_ENVIRONMENT in ["route_blockage", "compound_disruption"]:
            return {
                "coord": {"lon": 105.8412, "lat": 21.0245},
                "weather": [
                    {
                        "id": 501,
                        "main": "Rain",
                        "description": "heavy intensity rain and localized flooding",
                        "icon": "10d",
                    },
                    {
                        "id": 202,
                        "main": "Thunderstorm",
                        "description": "thunderstorm with heavy rain",
                        "icon": "11d",
                    },
                ],
                "base": "stations",
                "main": {
                    "temp": 298.48,
                    "feels_like": 298.74,
                    "temp_min": 297.56,
                    "temp_max": 300.05,
                    "pressure": 1015,
                    "humidity": 89,
                    "sea_level": 1015,
                    "grnd_level": 1013,
                },
                "visibility": 2000,
                "wind": {"speed": 12.5, "deg": 140, "gust": 18.2},
                "clouds": {"all": 90},
                "dt": 1661870592,
                "sys": {
                    "type": 2,
                    "id": 2004688,
                    "country": "VN",
                    "sunrise": 1661834187,
                    "sunset": 1661879324,
                },
                "timezone": 25200,
                "id": 1581130,
                "name": "Hanoi",
                "cod": 200,
                "alerts": [
                    {
                        "sender_name": "National Hydro-Meteorological Service",
                        "event": "Severe Flooding",
                        "start": 1661870592,
                        "end": 1661956992,
                        "description": "Expect heavy localized flooding. Avoid low-lying areas.",
                        "affected_zones": [
                            {"lat": 20.938611, "lng": 106.314444, "radius_km": 15},
                            {"lat": 20.850000, "lng": 106.450000, "radius_km": 10},
                        ],
                    }
                ],
            }
        return {
            "coord": {"lon": 105.8412, "lat": 21.0245},
            "weather": [
                {"id": 800, "main": "Clear", "description": "clear sky", "icon": "01d"}
            ],
            "base": "stations",
            "main": {
                "temp": 302.15,
                "feels_like": 305.82,
                "temp_min": 301.15,
                "temp_max": 303.15,
                "pressure": 1012,
                "humidity": 65,
            },
            "visibility": 10000,
            "wind": {"speed": 3.6, "deg": 120},
            "clouds": {"all": 0},
            "name": "Hanoi",
            "cod": 200,
        }

    @router.get("/mock/routes")
    def mock_routes() -> dict:
        global MOCK_ENVIRONMENT
        if MOCK_ENVIRONMENT in ["route_blockage", "compound_disruption"]:
            return {
                "geocoded_waypoints": [
                    {
                        "geocoder_status": "OK",
                        "place_id": "ChIJ_zX0nVQoNTERr2gQWwP1WlA",
                        "types": ["locality", "political"],
                    },
                    {
                        "geocoder_status": "OK",
                        "place_id": "ChIJIQBpAG2ocg0RsT57aPz_v0w",
                        "types": ["locality", "political"],
                    },
                ],
                "routes": [
                    {
                        "route_id": "R_BN_HN_MAIN",
                        "summary": "QL1A and QL5",
                        "legs": [
                            {
                                "distance": {"text": "35 km", "value": 35000},
                                "duration": {"text": "50 mins", "value": 3000},
                                "duration_in_traffic": {
                                    "text": "1 hours 10 mins",
                                    "value": 4200,
                                },
                                "steps": [],
                                "traffic_speed_entry": [],
                            }
                        ],
                        "warnings": [
                            "Severe flooding detected on QL1A near Bac Ninh.",
                            "Road closure ahead due to submerged lane.",
                            "Expect heavy delays and consider alternative routing.",
                        ],
                        "status": "Blocked",
                        "closure_probability": 0.95,
                        "incidents": [
                            {
                                "incident_id": "INC_001",
                                "type": "ROAD_CLOSED",
                                "description": "Lane submerged due to heavy flood",
                                "location": {"lat": 21.1861, "lng": 106.0763},
                            }
                        ],
                    }
                ],
                "status": "OK",
            }
        return {
            "geocoded_waypoints": [],
            "routes": [
                {
                    "route_id": "R_BN_HN_MAIN",
                    "summary": "QL1A and QL5",
                    "legs": [
                        {
                            "distance": {"text": "35 km", "value": 35000},
                            "duration": {"text": "50 mins", "value": 3000},
                            "duration_in_traffic": {
                                "text": "55 mins",
                                "value": 3300,
                            },
                        }
                    ],
                    "warnings": [],
                    "status": "Normal",
                    "closure_probability": 0.05,
                }
            ],
            "status": "OK",
        }

    @router.get("/mock/suppliers")
    def mock_suppliers() -> dict:
        global MOCK_ENVIRONMENT
        if MOCK_ENVIRONMENT in ["supplier_delay", "compound_disruption"]:
            return {
                "vendor_api_version": "v2.1",
                "timestamp": "2026-04-13T08:00:00Z",
                "vendors": [
                    {
                        "vendor_id": "SUP_BN",
                        "company_name": "Bac Ninh Precision Mfg",
                        "region": "Bac Ninh, VN",
                        "compliance_score": 0.92,
                        "facilities": [
                            {
                                "facility_id": "FAC_BN1",
                                "status": "Operational",
                                "capacity_utilization": 0.85,
                            },
                            {
                                "facility_id": "FAC_BN2",
                                "status": "Degraded",
                                "capacity_utilization": 0.30,
                                "active_alerts": [
                                    {
                                        "alert_code": "CRIT_LABOR_SHORTAGE",
                                        "severity": "HIGH",
                                        "message": "Significant labor shortage impacting production line 3.",
                                    },
                                    {
                                        "alert_code": "MATERIAL_DELAY",
                                        "severity": "MEDIUM",
                                        "message": "Raw material shipments delayed.",
                                    },
                                ],
                            },
                        ],
                        "fulfillment_metrics": {
                            "on_time_delivery_rate": 0.65,
                            "average_delay_hours": 48.5,
                            "defect_rate": 0.015,
                        },
                        "overall_status": "Delayed",
                    }
                ],
            }
        return {
            "vendor_api_version": "v2.1",
            "timestamp": "2026-04-13T08:00:00Z",
            "vendors": [
                {
                    "vendor_id": "SUP_BN",
                    "company_name": "Bac Ninh Precision Mfg",
                    "region": "Bac Ninh, VN",
                    "compliance_score": 0.94,
                    "facilities": [
                        {
                            "facility_id": "FAC_BN1",
                            "status": "Operational",
                            "capacity_utilization": 0.78,
                            "active_alerts": [],
                        }
                    ],
                    "fulfillment_metrics": {
                        "on_time_delivery_rate": 0.98,
                        "average_delay_hours": 2.1,
                        "defect_rate": 0.005,
                    },
                    "overall_status": "Normal",
                }
            ],
        }

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
    def get_inventory(
        search: str | None = None, status: str | None = None
    ) -> InventoryListResponse:
        runtime = runtime_getter()
        items = inventory_rows(runtime.state, search=search, status=status)
        return InventoryListResponse(items=items, total=len(items))

    @router.get("/suppliers", response_model=SupplierListResponse)
    def get_suppliers(
        sku: str | None = None, status: str | None = None
    ) -> SupplierListResponse:
        runtime = runtime_getter()
        items = supplier_rows(runtime.state, sku=sku, status=status)
        return SupplierListResponse(items=items, total=len(items))

    @router.get("/events", response_model=EventListResponse)
    def get_events(limit: int = 20) -> EventListResponse:
        runtime = runtime_getter()
        items = [
            item.model_copy(deep=True)
            for item in control_tower_summary(runtime.state).active_events[
                : max(limit, 0)
            ]
        ]
        return EventListResponse(items=items, total=len(runtime.state.active_events))

    @router.get("/plans/latest", response_model=PlanDetailResponse)
    def get_latest_plan() -> PlanDetailResponse:
        runtime = runtime_getter()
        return PlanDetailResponse(
            item=plan_view(runtime.state.pending_plan or runtime.state.latest_plan)
        )

    @router.get("/approvals/pending", response_model=PendingApprovalResponse)
    def get_pending_approval() -> PendingApprovalResponse:
        runtime = runtime_getter()
        return PendingApprovalResponse(item=pending_approval_view(runtime.state))

    @router.get("/approvals/{decision_id}", response_model=ApprovalDetailResponse)
    def get_approval(decision_id: str) -> ApprovalDetailResponse:
        runtime = runtime_getter()
        return ApprovalDetailResponse(
            item=approval_detail_view(runtime.state, decision_id)
        )

    @router.post(
        "/approvals/{decision_id}", response_model=ApprovalCommandResultResponse
    )
    def approval_command(
        decision_id: str, request: ApprovalCommandRequest
    ) -> ApprovalCommandResultResponse:
        runtime = runtime_getter()
        runtime.approval_command(decision_id, request.action)
        resolved_decision_id = runtime.current_decision_id() or decision_id
        return approval_command_result_view(
            runtime.state,
            decision_id=resolved_decision_id,
            action=request.action,
            execution=runtime.latest_execution(),
        )

    @router.post(
        "/approvals/{decision_id}/select-alternative",
        response_model=ApprovalCommandResultResponse,
    )
    def select_approval_alternative(
        decision_id: str, request: ApprovalAlternativeRequest
    ) -> ApprovalCommandResultResponse:
        runtime = runtime_getter()
        runtime.select_approval_alternative(decision_id, request.strategy_label)
        resolved_decision_id = runtime.current_decision_id() or decision_id
        return approval_command_result_view(
            runtime.state,
            decision_id=resolved_decision_id,
            action="select_alternative",
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

    @router.get(
        "/decision-logs/{decision_id}", response_model=DecisionLogDetailResponse
    )
    def get_decision_log_detail(decision_id: str) -> DecisionLogDetailResponse:
        runtime = runtime_getter()
        payload = runtime.store.get_decision_log(decision_id)
        if payload is None:
            raise_not_found("decision", decision_id)
        return DecisionLogDetailResponse(
            item=decision_detail_view(DecisionLog.model_validate(payload))
        )

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
        return {
            "summary": control_tower_summary(runtime.state).model_dump(mode="json"),
            "state": runtime.state.model_dump(mode="json"),
        }

    @router.post("/reset")
    def reset_state() -> dict:
        global MOCK_ENVIRONMENT
        MOCK_ENVIRONMENT = "normal"
        runtime = runtime_getter()
        runtime.reset()
        return {
            "summary": control_tower_summary(runtime.state).model_dump(mode="json"),
            "state": runtime.state.model_dump(mode="json"),
        }

    @router.post("/plan/daily")
    def daily_plan() -> dict:
        runtime = runtime_getter()
        try:
            runtime.run_daily()
        except HTTPException as exc:
            if exc.status_code == 409 and isinstance(exc.detail, dict):
                raise HTTPException(
                    status_code=409, detail=exc.detail["message"]
                ) from exc
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

    @router.get("/execution", response_model=ExecutionListResponse)
    def list_executions(limit: int = 50) -> ExecutionListResponse:
        runtime = runtime_getter()
        items = runtime.list_executions(limit=limit)
        return ExecutionListResponse(items=items, total=len(items))

    @router.get("/execution/{execution_id}", response_model=ExecutionDetailResponse)
    def get_execution(execution_id: str) -> ExecutionDetailResponse:
        runtime = runtime_getter()
        payload = runtime.store.get_execution_record(execution_id)
        if payload is not None:
            return ExecutionDetailResponse(item=execution_record_view(payload))

        # Try granular physical action records (prefix exec_)
        action_payload = runtime.store.get_action_execution_record(execution_id)
        if action_payload is not None:
            return ExecutionDetailResponse(
                item=action_execution_record_view(action_payload)
            )

        raise_not_found("execution", execution_id)

    @router.post("/execution/{plan_id}/dispatch", response_model=PlanDispatchResponse)
    def dispatch_plan(
        plan_id: str, request: DispatchModeRequest
    ) -> PlanDispatchResponse:
        runtime = runtime_getter()
        return PlanDispatchResponse(**runtime.dispatch_plan(plan_id, request.mode))

    @router.post(
        "/execution/{execution_id}/progress", response_model=ActionExecutionRecordView
    )
    def update_execution_progress(
        execution_id: str, request: ProgressRequest
    ) -> ActionExecutionRecordView:
        runtime = runtime_getter()
        return runtime.update_execution_progress(execution_id, request.percentage)

    @router.post(
        "/execution/{execution_id}/complete", response_model=ActionExecutionRecordView
    )
    def complete_execution(execution_id: str) -> ActionExecutionRecordView:
        runtime = runtime_getter()
        return runtime.complete_execution(execution_id)

    @router.post("/scenarios/run")
    def run_scenario(request: ScenarioRequest) -> dict:
        global MOCK_ENVIRONMENT
        MOCK_ENVIRONMENT = request.scenario_name
        runtime = runtime_getter()
        try:
            runtime.run_scenario(request.scenario_name, seed=request.seed)
        except HTTPException as exc:
            if exc.status_code == 409 and isinstance(exc.detail, dict):
                raise HTTPException(
                    status_code=409, detail=exc.detail["message"]
                ) from exc
            raise
        payload = runtime.legacy_response_payload()
        payload["scenario_history_count"] = len(runtime.state.scenario_history)
        return payload

    @router.post("/scenarios/run/stream")
    def stream_run_scenario(
        request: ScenarioRequest, background_tasks: BackgroundTasks
    ) -> dict:
        """
        Trigger a scenario run with streaming via WebSocket.
        """
        global MOCK_ENVIRONMENT
        MOCK_ENVIRONMENT = request.scenario_name
        from core.runtime_tracking import new_run_id

        run_id = new_run_id()
        background_tasks.add_task(
            _stream_scenario_plan,
            runtime_getter,
            run_id,
            request.scenario_name,
            request.seed,
        )
        return {
            "run_id": run_id,
            "ws_url": f"/ws/thinking/{run_id}",
        }

    @router.post("/decisions/{decision_id}/approve")
    def approve_decision(decision_id: str, request: LegacyApprovalRequest) -> dict:
        runtime = runtime_getter()
        runtime.approval_command(
            decision_id, "approve" if request.approve else "reject"
        )
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

    # ------------------------------------------------------------------
    # Streaming: WebSocket + trigger endpoint
    # ------------------------------------------------------------------

    @router.post("/plan/daily/stream")
    async def daily_plan_stream(background_tasks: BackgroundTasks) -> dict:
        """
        Trigger a daily-plan run with streaming.

        Flow:
            1. Client calls POST /plan/daily/stream â†’ receives {run_id, ws_url}
            2. Client connects to WS /ws/thinking/{run_id} â†’ receives real-time ThinkingEvents
            3. After graph completion, server closes WS channel (sentinel None)

        Backward compat: Legacy endpoint POST /plan/daily remains independent.
        """
        from core.runtime_tracking import new_run_id

        run_id = new_run_id()
        background_tasks.add_task(_stream_daily_plan, runtime_getter, run_id)
        return {
            "run_id": run_id,
            "ws_url": f"/ws/thinking/{run_id}",
        }

    @router.websocket("/ws/thinking/{run_id}")
    async def websocket_thinking_stream(websocket: WebSocket, run_id: str) -> None:
        """
        WebSocket endpoint for real-time thinking/reasoning stream.

        Subscribes to the event bus for the given run_id and sends
        a combined payload of the current event and the full trace update.
        """
        from streaming.event_bus import event_bus

        await websocket.accept()
        runtime = runtime_getter()
        try:
            async for event in event_bus.subscribe(run_id):
                if event is None:
                    break

                # Send a combined payload: the specific event + the overall trace snapshot
                payload = {
                    "event": event.model_dump(mode="json"),
                    "trace": latest_trace_view(runtime.state).model_dump(mode="json"),
                }
                await websocket.send_json(payload)
        except WebSocketDisconnect:
            pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    return router


# ------------------------------------------------------------------
# Background task helpers (module-level â€” outside create_router)
# ------------------------------------------------------------------


async def _stream_daily_plan(runtime_getter: Callable, run_id: str) -> None:
    """
    Runs the graph in a threadpool executor to avoid blocking the event loop.
    Ensures event_bus.close() is always called, even on exception.
    """
    from streaming.event_bus import event_bus
    from streaming.schemas import ThinkingEvent

    loop = asyncio.get_event_loop()
    runtime = runtime_getter()
    try:
        await loop.run_in_executor(
            None,
            lambda: _sync_run_with_run_id(runtime, run_id),
        )
    except Exception as exc:
        # Emit error event before closing the channel
        event_bus.publish(
            run_id,
            ThinkingEvent(
                type="error",
                agent="system",
                step="fatal",
                message=f"{exc.__class__.__name__}: {exc}",
                data={"exception": exc.__class__.__name__},
            ),
        )
    finally:
        event_bus.close(run_id)


def _sync_run_with_run_id(runtime, run_id: str) -> None:
    """
    Sync wrapper â€” runs in thread pool.
    Calls graph.invoke() with run_id so _emit() calls can publish to the bus.
    Saves state and artifacts after completion (mirrors run_daily logic).
    """
    from orchestrator.service import (
        _save_state,
        ensure_no_pending_plan,
    )

    ensure_no_pending_plan(runtime.state)
    # graph.invoke() forwards run_id into OrchestrationState
    # so every _emit() in nodes will publish to event_bus
    updated = runtime.graph.invoke(runtime.state, None, run_id=run_id)
    _save_state(updated, runtime.store)
    runtime.state = updated


async def _stream_scenario_plan(
    runtime_getter: Callable, run_id: str, scenario_name: str, seed: int
) -> None:
    from streaming.event_bus import event_bus
    from streaming.schemas import ThinkingEvent

    loop = asyncio.get_event_loop()
    runtime = runtime_getter()
    try:
        await loop.run_in_executor(
            None,
            lambda: _sync_scenario_with_run_id(runtime, run_id, scenario_name, seed),
        )
    except Exception as exc:
        event_bus.publish(
            run_id,
            ThinkingEvent(
                type="error",
                agent="system",
                step="fatal",
                message=f"{exc.__class__.__name__}: {exc}",
                data={"exception": exc.__class__.__name__},
            ),
        )
    finally:
        event_bus.close(run_id)


def _sync_scenario_with_run_id(
    runtime, run_id: str, scenario_name: str, seed: int
) -> None:
    # run_scenario internally calls graph.invoke via ScenarioRunner
    # and handles Saving artifacts
    runtime.run_scenario(scenario_name, seed=seed, run_id=run_id)
