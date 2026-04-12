from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from core.enums import ExecutionStatus, PlanExecutionStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_idempotency_key(plan_id: str, action_id: str, approval_timestamp: str) -> str:
    """Deterministic key — safe to retry as many times as needed."""
    raw = f"{plan_id}:{action_id}:{approval_timestamp}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# DispatchResult — returned by every Adapter
# ---------------------------------------------------------------------------

class DispatchResult(BaseModel):
    success: bool
    receipt: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    # True  → transient error (network timeout, rate-limit) → retry allowed
    # False → permanent error (invalid SKU, business rule)  → escalate immediately
    is_retryable: bool = False


# ---------------------------------------------------------------------------
# ExecutionRecord — the "receipt" for every dispatched action
# ---------------------------------------------------------------------------

class ExecutionRecord(BaseModel):
    execution_id: str
    plan_id: str
    action_id: str
    action_type: str
    target_system: str                         # "ERP" | "WMS" | "TMS"
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str

    status: ExecutionStatus = ExecutionStatus.PLANNED
    receipt: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None
    is_retryable: bool = False                 # copied from last DispatchResult

    created_at: datetime = Field(default_factory=utc_now)
    dispatched_at: datetime | None = None
    applied_at: datetime | None = None
    
    # --- Physical Tracking Fields (Added for Manual Confirmation) ---
    estimated_completion_at: datetime | None = None
    progress_percentage: float = 0.0          # Manual updates (0-100)

    def mark_completed(self) -> None:
        """Called when a person (Warehouse Staff) manually confirms arrival."""
        self.status = ExecutionStatus.COMPLETED
        self.progress_percentage = 100.0
        self.applied_at = utc_now()  # Final arrival time

    def set_progress(self, percentage: float) -> None:
        """Manual progress update by staff/systems."""
        self.progress_percentage = round(min(max(percentage, 0.0), 99.9), 1)
        if self.progress_percentage > 0:
            self.status = ExecutionStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# DispatchRequest  — input to ActionDispatchService
# ---------------------------------------------------------------------------

class DispatchRequest(BaseModel):
    plan_id: str
    mode: str = "dry_run"                      # "dry_run" | "commit"


# ---------------------------------------------------------------------------
# PlanDispatchSummary — aggregate result for the whole plan
# ---------------------------------------------------------------------------

class PlanDispatchSummary(BaseModel):
    plan_id: str
    dispatch_mode: str
    plan_execution_status: PlanExecutionStatus
    overall_progress: float = 0.0               # Aggregate progress of all actions
    records: list[ExecutionRecord]
    compensation_hints: list[str] = Field(default_factory=list)
