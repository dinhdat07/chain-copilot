from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from core.enums import EventType


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
    mode: str
    status: str
    score: float
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    strategy_label: str | None = None
    generated_by: str | None = None
    approval_required: bool = False
    approval_reason: str = ""
    planner_reasoning: str = ""
    llm_planner_narrative: str | None = None
    critic_summary: str | None = None
    trigger_event_ids: list[str] = Field(default_factory=list)
    actions: list[ActionView] = Field(default_factory=list)


class PendingApprovalView(BaseModel):
    decision_id: str
    approval_status: str
    approval_reason: str
    plan: PlanView


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
    agent: str
    summary: str
    observations: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    downstream_impacts: list[str] = Field(default_factory=list)
    recommended_action_ids: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    llm_used: bool = False
    llm_error: str | None = None


class TraceView(BaseModel):
    mode: str
    current_branch: str
    event: EventView | None = None
    steps: list[AgentStepView] = Field(default_factory=list)
    latest_plan: PlanView | None = None
    decision_id: str | None = None
    selection_reason: str | None = None
    candidate_evaluations: list[CandidateEvaluationView] = Field(default_factory=list)
    approval_pending: bool = False


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


class PlanDetailResponse(BaseModel):
    item: PlanView | None = None


class PendingApprovalResponse(BaseModel):
    item: PendingApprovalView | None = None


class DecisionLogListResponse(BaseModel):
    items: list[DecisionLogSummaryView]


class DecisionLogDetailResponse(BaseModel):
    item: DecisionLogDetailView


class TraceResponse(BaseModel):
    item: TraceView


class ReflectionListResponse(BaseModel):
    items: list[ReflectionView]
    scenarios: list[ScenarioOutcomeView]
    pattern_tag_counts: dict[str, int] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False
