from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from core.enums import EventType
from core.runtime_records import DispatchMode, EventClass, ExecutionStatus, RunStatus, RunType


class ScenarioRequest(BaseModel):
    scenario_name: str
    seed: int = 7


class WhatIfRequest(BaseModel):
    scenario_name: str
    seed: int = 7


class EventRequest(BaseModel):
    type: EventType
    severity: float = Field(ge=0.0, le=1.0)
    source: str = "api"
    entity_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class LegacyApprovalRequest(BaseModel):
    approve: bool = True


class ApprovalCommandRequest(BaseModel):
    action: Literal["approve", "reject", "safer_plan"]


class EventIngestRequest(BaseModel):
    event_class: EventClass
    event_type: str
    source: str = "api"
    occurred_at: datetime | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    idempotency_key: str | None = None
    severity: float = Field(default=0.0, ge=0.0, le=1.0)
    entity_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class KPIView(BaseModel):
    service_level: float
    total_cost: float
    disruption_risk: float
    recovery_speed: float
    stockout_risk: float
    decision_latency_ms: float


class AlertView(BaseModel):
    level: Literal["info", "warning", "critical"]
    title: str
    message: str
    source: str
    event_type: str | None = None
    entity_ids: list[str] = Field(default_factory=list)


class EventView(BaseModel):
    event_id: str
    type: str
    severity: float
    source: str
    entity_ids: list[str] = Field(default_factory=list)
    occurred_at: datetime
    detected_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class EventEnvelopeView(BaseModel):
    event_id: str
    event_class: str
    event_type: str
    source: str
    occurred_at: datetime
    ingested_at: datetime
    correlation_id: str
    causation_id: str | None = None
    idempotency_key: str
    severity: float
    entity_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class ActionView(BaseModel):
    action_id: str
    action_type: str
    target_id: str
    reason: str
    priority: float
    estimated_cost_delta: float
    estimated_service_delta: float
    estimated_risk_delta: float
    estimated_recovery_hours: float
    parameters: dict[str, Any] = Field(default_factory=dict)


class CandidateEvaluationView(BaseModel):
    strategy_label: str
    action_ids: list[str] = Field(default_factory=list)
    score: float
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    projected_kpis: KPIView
    approval_required: bool
    approval_reason: str
    rationale: str
    llm_used: bool = False


class PlanView(BaseModel):
    plan_id: str
    decision_id: str | None = None
    mode: str
    status: str
    score: float
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    strategy_label: str | None = None
    generated_by: str | None = None
    approval_required: bool = False
    approval_reason: str = ""
    approval_status: str = "not_required"
    planner_reasoning: str = ""
    llm_planner_narrative: str | None = None
    critic_summary: str | None = None
    trigger_event_ids: list[str] = Field(default_factory=list)
    actions: list[ActionView] = Field(default_factory=list)


class PendingApprovalView(BaseModel):
    decision_id: str
    approval_status: str
    approval_reason: str
    allowed_actions: list[str] = Field(default_factory=lambda: ["approve", "reject", "safer_plan"])
    blocking_operations: list[str] = Field(default_factory=lambda: ["plan_daily", "scenario_run"])
    selection_reason: str = ""
    selected_actions: list[str] = Field(default_factory=list)
    before_kpis: KPIView
    projected_kpis: KPIView
    candidate_count: int = 0
    plan: PlanView


class ApprovalDetailView(BaseModel):
    decision_id: str
    plan_id: str
    approval_required: bool
    approval_status: str
    approval_reason: str
    is_pending: bool = False
    allowed_actions: list[str] = Field(default_factory=list)
    selection_reason: str = ""
    selected_actions: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    before_kpis: KPIView
    after_kpis: KPIView
    candidate_count: int = 0
    plan: PlanView


class ApprovalCommandResultResponse(BaseModel):
    decision_id: str
    action: str
    approval_status: str
    message: str
    latest_plan: PlanView | None = None
    pending_approval: PendingApprovalView | None = None
    execution: "ExecutionRecordView | None" = None
    latest_trace: "TraceView | None" = None
    summary: "ControlTowerSummaryResponse | None" = None


class DecisionLogSummaryView(BaseModel):
    decision_id: str
    plan_id: str
    approval_status: str
    approval_required: bool
    approval_reason: str
    selection_reason: str
    selected_actions: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    llm_used: bool = False


class DecisionLogDetailView(BaseModel):
    decision_id: str
    plan_id: str
    approval_status: str
    approval_required: bool
    approval_reason: str
    rationale: str
    selection_reason: str
    winning_factors: list[str] = Field(default_factory=list)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    selected_actions: list[str] = Field(default_factory=list)
    rejected_actions: list[dict[str, str]] = Field(default_factory=list)
    candidate_evaluations: list[CandidateEvaluationView] = Field(default_factory=list)
    critic_summary: str | None = None
    critic_findings: list[str] = Field(default_factory=list)
    llm_used: bool = False
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_error: str | None = None
    before_kpis: KPIView
    after_kpis: KPIView


class InventoryRowView(BaseModel):
    sku: str
    warehouse_id: str
    on_hand: int
    incoming_qty: int
    forecast_qty: int
    reorder_point: int
    safety_stock: int
    unit_cost: float
    status: str
    preferred_supplier_id: str
    preferred_route_id: str


class SupplierRowView(BaseModel):
    supplier_id: str
    sku: str
    unit_cost: float
    lead_time_days: int
    reliability: float
    is_primary: bool
    status: str
    tradeoff: str


class AgentStepView(BaseModel):
    step_id: str | None = None
    sequence: int = 0
    agent: str
    node_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: float | None = None
    mode_snapshot: str
    summary: str
    reasoning_source: str = ""
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    output_snapshot: dict[str, Any] = Field(default_factory=dict)
    observations: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    downstream_impacts: list[str] = Field(default_factory=list)
    recommended_action_ids: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    llm_used: bool = False
    llm_error: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None


class RouteDecisionView(BaseModel):
    from_node: str
    outcome: str
    to_node: str
    reason: str = ""


class TraceView(BaseModel):
    run_id: str | None = None
    trace_id: str | None = None
    status: str = "idle"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    mode_before: str | None = None
    mode_after: str | None = None
    mode: str
    current_branch: str
    terminal_stage: str | None = None
    event: EventView | None = None
    route_decisions: list[RouteDecisionView] = Field(default_factory=list)
    steps: list[AgentStepView] = Field(default_factory=list)
    latest_plan: PlanView | None = None
    decision_id: str | None = None
    selected_strategy: str | None = None
    candidate_count: int = 0
    selection_reason: str | None = None
    candidate_evaluations: list[CandidateEvaluationView] = Field(default_factory=list)
    approval_pending: bool = False
    approval_reason: str = ""
    execution_status: str | None = None
    critic_summary: str | None = None


class SelectedPlanSummaryView(BaseModel):
    plan_id: str
    strategy_label: str | None = None
    generated_by: str | None = None
    approval_required: bool = False
    approval_reason: str = ""
    score: float = 0.0
    action_ids: list[str] = Field(default_factory=list)


class ExecutionSummaryView(BaseModel):
    status: str
    dispatch_mode: str
    action_ids: list[str] = Field(default_factory=list)


class RunView(BaseModel):
    run_id: str
    run_type: RunType
    parent_run_id: str | None = None
    correlation_id: str
    trigger_event_id: str | None = None
    input_event_ids: list[str] = Field(default_factory=list)
    mode_before: str
    mode_after: str
    status: RunStatus
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: float = 0.0
    decision_id: str | None = None
    selected_plan_id: str | None = None
    execution_id: str | None = None
    approval_status: str | None = None
    llm_fallback_used: bool = False
    llm_fallback_reason: str | None = None
    selected_plan_summary: SelectedPlanSummaryView | None = None
    execution_summary: ExecutionSummaryView | None = None


class ExecutionReceiptView(BaseModel):
    receipt_id: str
    action_id: str
    status: str
    detail: str = ""


class ExecutionTransitionView(BaseModel):
    status: str
    timestamp: datetime
    reason: str = ""


class ExecutionRecordView(BaseModel):
    execution_id: str
    run_id: str
    decision_id: str | None = None
    plan_id: str | None = None
    status: ExecutionStatus
    dispatch_mode: DispatchMode
    dry_run: bool = False
    target_system: str
    action_ids: list[str] = Field(default_factory=list)
    receipts: list[ExecutionReceiptView] = Field(default_factory=list)
    status_history: list[ExecutionTransitionView] = Field(default_factory=list)
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class ReflectionView(BaseModel):
    note_id: str
    run_id: str
    scenario_id: str
    plan_id: str | None = None
    mode: str
    approval_status: str
    summary: str
    lessons: list[str] = Field(default_factory=list)
    pattern_tags: list[str] = Field(default_factory=list)
    follow_up_checks: list[str] = Field(default_factory=list)
    llm_used: bool = False
    llm_error: str | None = None


class ScenarioOutcomeView(BaseModel):
    scenario_id: str
    runs: int
    latest_run_id: str | None = None
    latest_plan_id: str | None = None
    latest_approval_status: str | None = None
    latest_reflection_status: str | None = None
    latest_kpis: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)


class ControlTowerSummaryResponse(BaseModel):
    mode: str
    kpis: KPIView
    alerts: list[AlertView] = Field(default_factory=list)
    active_events: list[EventView] = Field(default_factory=list)
    latest_plan: PlanView | None = None
    pending_approval: PendingApprovalView | None = None
    decision_count: int = 0
    scenario_history_count: int = 0


class ControlTowerStateResponse(BaseModel):
    summary: ControlTowerSummaryResponse
    inventory: list[InventoryRowView] = Field(default_factory=list)
    suppliers: list[SupplierRowView] = Field(default_factory=list)
    reflections: list[ReflectionView] = Field(default_factory=list)
    latest_trace: TraceView | None = None


class InventoryListResponse(BaseModel):
    items: list[InventoryRowView]
    total: int


class SupplierListResponse(BaseModel):
    items: list[SupplierRowView]
    total: int


class EventListResponse(BaseModel):
    items: list[EventView]
    total: int


class EventIngestResponse(BaseModel):
    event: EventEnvelopeView
    accepted: bool = True
    run_id: str | None = None
    execution_id: str | None = None


class PlanDetailResponse(BaseModel):
    item: PlanView | None = None


class PendingApprovalResponse(BaseModel):
    item: PendingApprovalView | None = None


class ApprovalDetailResponse(BaseModel):
    item: ApprovalDetailView


class DecisionLogListResponse(BaseModel):
    items: list[DecisionLogSummaryView]


class DecisionLogDetailResponse(BaseModel):
    item: DecisionLogDetailView


class TraceResponse(BaseModel):
    item: TraceView


class RunDetailResponse(BaseModel):
    item: RunView


class RunListResponse(BaseModel):
    items: list[RunView]
    total: int


class RunStateResponse(BaseModel):
    run: RunView
    state: ControlTowerStateResponse


class ExecutionDetailResponse(BaseModel):
    item: ExecutionRecordView


class ReflectionListResponse(BaseModel):
    items: list[ReflectionView]
    scenarios: list[ScenarioOutcomeView]
    pattern_tag_counts: dict[str, int] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False
    correlation_id: str | None = None


ApprovalCommandResultResponse.model_rebuild()
