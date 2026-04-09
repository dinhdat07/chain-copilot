from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from core.enums import ActionType, ApprovalStatus, EventType, Mode, PlanStatus


class KPIState(BaseModel):
    service_level: float = Field(ge=0.0, le=1.0)
    total_cost: float = Field(ge=0.0)
    disruption_risk: float = Field(ge=0.0, le=1.0)
    recovery_speed: float = Field(ge=0.0, le=1.0)
    stockout_risk: float = Field(ge=0.0, le=1.0)
    decision_latency_ms: float = Field(default=0.0, ge=0.0)


class OrderRecord(BaseModel):
    order_id: str
    sku: str
    day_index: int = Field(ge=0)
    quantity: int = Field(ge=0)
    warehouse_id: str


class InventoryItem(BaseModel):
    sku: str
    on_hand: int = Field(ge=0)
    incoming_qty: int = Field(default=0, ge=0)
    reorder_point: int = Field(ge=0)
    safety_stock: int = Field(ge=0)
    unit_cost: float = Field(ge=0.0)
    preferred_supplier_id: str
    preferred_route_id: str
    warehouse_id: str
    forecast_qty: int = Field(default=0, ge=0)


class SupplierRecord(BaseModel):
    supplier_id: str
    sku: str
    unit_cost: float = Field(ge=0.0)
    lead_time_days: int = Field(ge=0)
    reliability: float = Field(ge=0.0, le=1.0)
    is_primary: bool = False
    status: str = "active"


class RouteRecord(BaseModel):
    route_id: str
    origin: str
    destination: str
    transit_days: int = Field(ge=0)
    cost: float = Field(ge=0.0)
    risk_score: float = Field(ge=0.0, le=1.0)
    status: str = "active"


class WarehouseRecord(BaseModel):
    warehouse_id: str
    name: str
    capacity: int = Field(ge=0)
    region: str


class Event(BaseModel):
    event_id: str
    type: EventType
    source: str
    severity: float = Field(ge=0.0, le=1.0)
    entity_ids: list[str] = Field(default_factory=list)
    occurred_at: datetime
    detected_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str

    @model_validator(mode="after")
    def validate_times(self) -> "Event":
        if self.detected_at < self.occurred_at:
            raise ValueError("detected_at must be greater than or equal to occurred_at")
        return self


class Action(BaseModel):
    action_id: str
    action_type: ActionType
    target_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    estimated_cost_delta: float = 0.0
    estimated_service_delta: float = 0.0
    estimated_risk_delta: float = 0.0
    estimated_recovery_hours: float = 0.0
    reason: str = ""
    priority: float = 0.0


class AgentProposal(BaseModel):
    agent: str
    observations: list[str] = Field(default_factory=list)
    proposals: list[Action] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    domain_summary: str = ""
    downstream_impacts: list[str] = Field(default_factory=list)
    recommended_action_ids: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    notes_for_planner: str = ""
    llm_used: bool = False
    llm_error: str | None = None


class CandidatePlanDraft(BaseModel):
    strategy_label: str
    action_ids: list[str] = Field(default_factory=list)
    rationale: str = ""
    llm_used: bool = False


class CandidatePlanEvaluation(BaseModel):
    strategy_label: str
    action_ids: list[str] = Field(default_factory=list)
    score: float
    score_breakdown: dict[str, float]
    projected_kpis: KPIState
    approval_required: bool = False
    approval_reason: str = ""
    rationale: str = ""
    llm_used: bool = False


class Plan(BaseModel):
    plan_id: str
    mode: Mode
    trigger_event_ids: list[str] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    score: float
    score_breakdown: dict[str, float]
    strategy_label: str | None = None
    generated_by: str | None = None
    approval_required: bool = False
    approval_reason: str = ""
    planner_reasoning: str = ""
    llm_planner_narrative: str | None = None
    critic_summary: str | None = None
    status: PlanStatus = PlanStatus.PROPOSED


class DecisionLog(BaseModel):
    decision_id: str
    plan_id: str
    event_ids: list[str] = Field(default_factory=list)
    before_kpis: KPIState
    after_kpis: KPIState
    selected_actions: list[str] = Field(default_factory=list)
    rejected_actions: list[dict[str, str]] = Field(default_factory=list)
    score_breakdown: dict[str, float]
    rationale: str
    candidate_evaluations: list[CandidatePlanEvaluation] = Field(default_factory=list)
    selection_reason: str = ""
    winning_factors: list[str] = Field(default_factory=list)
    approval_required: bool = False
    approval_reason: str = ""
    planner_error: str | None = None
    llm_operator_explanation: str | None = None
    llm_approval_summary: str | None = None
    llm_used: bool = False
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_error: str | None = None
    critic_summary: str | None = None
    critic_findings: list[str] = Field(default_factory=list)
    critic_used: bool = False
    critic_error: str | None = None
    approval_status: ApprovalStatus = ApprovalStatus.NOT_REQUIRED


class MemorySnapshot(BaseModel):
    snapshot_id: str
    timestamp: datetime
    supplier_reliability: dict[str, float] = Field(default_factory=dict)
    route_disruption_priors: dict[str, float] = Field(default_factory=dict)
    scenario_outcomes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    last_approved_plan_ids: list[str] = Field(default_factory=list)


class ScenarioRun(BaseModel):
    run_id: str
    scenario_id: str
    seed: int
    events: list[Event]
    result_plan_id: str | None = None
    result_kpis: KPIState | None = None
    outcome_summary: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = Field(default=0.0, ge=0.0)
    status: str = "pending"


class SystemState(BaseModel):
    run_id: str
    mode: Mode = Mode.NORMAL
    timestamp: datetime
    inventory: dict[str, InventoryItem] = Field(default_factory=dict)
    suppliers: dict[str, SupplierRecord] = Field(default_factory=dict)
    routes: dict[str, RouteRecord] = Field(default_factory=dict)
    warehouses: dict[str, WarehouseRecord] = Field(default_factory=dict)
    orders: list[OrderRecord] = Field(default_factory=list)
    kpis: KPIState
    active_events: list[Event] = Field(default_factory=list)
    latest_plan_id: str | None = None
    latest_plan: Plan | None = None
    pending_plan: Plan | None = None
    decision_logs: list[DecisionLog] = Field(default_factory=list)
    candidate_actions: list[Action] = Field(default_factory=list)
    agent_outputs: dict[str, AgentProposal] = Field(default_factory=dict)
    memory: MemorySnapshot | None = None
    scenario_history: list[ScenarioRun] = Field(default_factory=list)
    extra_cost: float = Field(default=0.0, ge=0.0)

    @field_validator("active_events")
    @classmethod
    def dedupe_events(cls, value: list[Event]) -> list[Event]:
        seen: set[str] = set()
        result: list[Event] = []
        for event in value:
            if event.dedupe_key in seen:
                continue
            seen.add(event.dedupe_key)
            result.append(event)
        return result
