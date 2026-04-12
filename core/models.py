from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from core.enums import ActionType, ApprovalStatus, ConstraintViolationCode, EventType, Mode, PlanStatus


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
    name: str = "Unknown SKU"
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
    capacity: int = Field(default=9999, ge=0)


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


class ConstraintViolation(BaseModel):
    code: ConstraintViolationCode
    message: str
    action_id: str | None = None
    severity: str = "hard"


class CandidatePlanEvaluation(BaseModel):
    strategy_label: str
    action_ids: list[str] = Field(default_factory=list)
    score: float
    score_breakdown: dict[str, float]
    projected_kpis: KPIState
    feasible: bool = True
    violations: list[ConstraintViolation] = Field(default_factory=list)
    mode_rationale: str = ""
    approval_required: bool = False
    approval_reason: str = ""
    rationale: str = ""
    llm_used: bool = False


class HistoricalCase(BaseModel):
    case_id: str
    event_type: str
    event_severity: float = 0.0
    actions_taken: list[str] = Field(default_factory=list)
    outcome_kpis: dict[str, float] = Field(default_factory=dict)
    reflection_notes: str = ""
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)


class PlanMetadata(BaseModel):
    referenced_cases: list[HistoricalCase] = Field(default_factory=list)
    memory_influence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    strategy_rationale: str = ""
    strategic_prompt: str = ""


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
    feasible: bool = True
    violations: list[ConstraintViolation] = Field(default_factory=list)
    mode_rationale: str = ""
    metadata: PlanMetadata = Field(default_factory=PlanMetadata)


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
    feasible: bool = True
    violations: list[ConstraintViolation] = Field(default_factory=list)
    mode_rationale: str = ""
    metadata: PlanMetadata = Field(default_factory=PlanMetadata)



class ReflectionNote(BaseModel):
    note_id: str
    run_id: str
    scenario_id: str
    plan_id: str | None = None
    event_types: list[str] = Field(default_factory=list)
    mode: str
    approval_status: str
    summary: str
    lessons: list[str] = Field(default_factory=list)
    pattern_tags: list[str] = Field(default_factory=list)
    follow_up_checks: list[str] = Field(default_factory=list)
    llm_used: bool = False
    llm_error: str | None = None


class TraceRouteDecision(BaseModel):
    from_node: str
    outcome: str
    to_node: str
    reason: str = ""


class TraceStep(BaseModel):
    step_id: str | None = None
    sequence: int = 0
    node_key: str
    node_type: str
    status: str = "running"
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0.0)
    mode_snapshot: str
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    output_snapshot: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    reasoning_source: str = ""
    observations: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    downstream_impacts: list[str] = Field(default_factory=list)
    recommended_action_ids: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    llm_used: bool = False
    llm_error: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None


class OrchestrationTrace(BaseModel):
    trace_id: str
    run_id: str
    started_at: datetime
    completed_at: datetime | None = None
    mode_before: str
    mode_after: str | None = None
    current_branch: str = "normal"
    terminal_stage: str | None = None
    status: str = "running"
    event: Event | None = None
    route_decisions: list[TraceRouteDecision] = Field(default_factory=list)
    steps: list[TraceStep] = Field(default_factory=list)
    decision_id: str | None = None
    selected_plan_id: str | None = None
    selected_strategy: str | None = None
    candidate_count: int = 0
    selection_reason: str | None = None
    approval_pending: bool = False
    approval_reason: str = ""
    execution_status: str | None = None
    critic_summary: str | None = None


class MemorySnapshot(BaseModel):
    snapshot_id: str
    timestamp: datetime
    supplier_reliability: dict[str, float] = Field(default_factory=dict)
    route_disruption_priors: dict[str, float] = Field(default_factory=dict)
    scenario_outcomes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    last_approved_plan_ids: list[str] = Field(default_factory=list)
    reflection_notes: list[ReflectionNote] = Field(default_factory=list)
    pattern_tag_counts: dict[str, int] = Field(default_factory=dict)
    historical_cases: list[HistoricalCase] = Field(default_factory=list)


class ScenarioRun(BaseModel):
    run_id: str
    scenario_id: str
    seed: int
    events: list[Event]
    result_plan_id: str | None = None
    decision_id: str | None = None
    result_kpis: KPIState | None = None
    outcome_summary: dict[str, Any] = Field(default_factory=dict)
    approval_status: str | None = None
    reflection_status: str = "pending"
    reflection_note_id: str | None = None
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
    latest_trace: OrchestrationTrace | None = None
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

# Alias for backward compatibility after consolidation
Violation = ConstraintViolation
