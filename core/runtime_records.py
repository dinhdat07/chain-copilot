from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RunType(str, Enum):
    DAILY_CYCLE = "daily_cycle"
    EVENT_RESPONSE = "event_response"
    SCENARIO_STEP = "scenario_step"
    APPROVAL_RESOLUTION = "approval_resolution"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EventClass(str, Enum):
    COMMAND = "command"
    DOMAIN = "domain"
    SYSTEM = "system"


class ExecutionStatus(str, Enum):
    PLANNED = "planned"
    APPROVAL_PENDING = "approval_pending"
    APPROVED = "approved"
    DISPATCHED = "dispatched"
    APPLIED = "applied"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


class DispatchMode(str, Enum):
    SIMULATION = "simulation"
    PRODUCTION = "production"


class EventEnvelope(BaseModel):
    event_id: str
    event_class: EventClass
    event_type: str
    source: str
    occurred_at: datetime
    ingested_at: datetime
    correlation_id: str
    causation_id: str | None = None
    idempotency_key: str
    severity: float = Field(default=0.0, ge=0.0, le=1.0)
    entity_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class SelectedPlanSummary(BaseModel):
    plan_id: str
    strategy_label: str | None = None
    generated_by: str | None = None
    approval_required: bool = False
    approval_reason: str = ""
    score: float = 0.0
    action_ids: list[str] = Field(default_factory=list)


class ExecutionSummary(BaseModel):
    status: ExecutionStatus
    dispatch_mode: DispatchMode = DispatchMode.SIMULATION
    action_ids: list[str] = Field(default_factory=list)


class ExecutionReceipt(BaseModel):
    receipt_id: str
    action_id: str
    status: str
    detail: str = ""


class ExecutionTransition(BaseModel):
    status: ExecutionStatus
    timestamp: datetime
    reason: str = ""


class ExecutionRecord(BaseModel):
    execution_id: str
    run_id: str
    decision_id: str | None = None
    plan_id: str | None = None
    status: ExecutionStatus
    dispatch_mode: DispatchMode = DispatchMode.SIMULATION
    dry_run: bool = False
    target_system: str = "digital_twin"
    action_ids: list[str] = Field(default_factory=list)
    receipts: list[ExecutionReceipt] = Field(default_factory=list)
    status_history: list[ExecutionTransition] = Field(default_factory=list)
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class RunRecord(BaseModel):
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
    duration_ms: float = Field(default=0.0, ge=0.0)
    decision_id: str | None = None
    selected_plan_id: str | None = None
    execution_id: str | None = None
    approval_status: str | None = None
    llm_fallback_used: bool = False
    llm_fallback_reason: str | None = None
    selected_plan_summary: SelectedPlanSummary | None = None
    execution_summary: ExecutionSummary | None = None
