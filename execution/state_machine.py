from __future__ import annotations

from core.enums import ExecutionStatus, PlanExecutionStatus
from execution.models import ExecutionRecord


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class InvalidTransitionError(Exception):
    """Raised when an illegal state transition is attempted."""


# ---------------------------------------------------------------------------
# Allowed transitions (Action-level)
# ---------------------------------------------------------------------------

_ALLOWED: dict[ExecutionStatus, set[ExecutionStatus]] = {
    ExecutionStatus.PLANNED:          {ExecutionStatus.APPROVAL_PENDING, ExecutionStatus.APPROVED},
    ExecutionStatus.APPROVAL_PENDING: {ExecutionStatus.APPROVED, ExecutionStatus.FAILED},
    ExecutionStatus.APPROVED:         {ExecutionStatus.DISPATCHED},
    ExecutionStatus.DISPATCHED:       {ExecutionStatus.APPLIED, ExecutionStatus.FAILED},
    ExecutionStatus.APPLIED:          {ExecutionStatus.IN_PROGRESS, ExecutionStatus.COMPLETED},
    ExecutionStatus.IN_PROGRESS:      {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED},
    ExecutionStatus.FAILED:           {ExecutionStatus.ROLLED_BACK},
    ExecutionStatus.COMPLETED:        set(),   # Physical Terminal
    ExecutionStatus.ROLLED_BACK:      set(),   # Terminal
}


def transition(record: ExecutionRecord, new_status: ExecutionStatus) -> ExecutionRecord:
    """Mutates record.status if the transition is valid, otherwise raises."""
    if record.status == new_status:
        return record  # No change
        
    allowed = _ALLOWED.get(record.status, set())
    if new_status not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition {record.execution_id} "
            f"from {record.status} → {new_status}. "
            f"Allowed: {[s.value for s in allowed]}"
        )
    record.status = new_status
    return record


# ---------------------------------------------------------------------------
# Plan-level aggregation
# ---------------------------------------------------------------------------

def compute_plan_execution_status(records: list[ExecutionRecord]) -> PlanExecutionStatus:
    """Derives the overall plan execution status from individual records."""
    if not records:
        return PlanExecutionStatus.PENDING

    statuses = {r.status for r in records}
    finished_success = {ExecutionStatus.APPLIED, ExecutionStatus.COMPLETED}
    failed_states = {ExecutionStatus.FAILED, ExecutionStatus.ROLLED_BACK}

    if statuses and statuses.issubset(finished_success):
        return PlanExecutionStatus.COMPLETED

    if statuses & failed_states:
        return PlanExecutionStatus.REQUIRES_MANUAL_INTERVENTION

    if statuses & {ExecutionStatus.IN_PROGRESS, ExecutionStatus.APPLIED, ExecutionStatus.DISPATCHED}:
        return PlanExecutionStatus.PARTIALLY_APPLIED

    return PlanExecutionStatus.PENDING


def compute_overall_progress(records: list[ExecutionRecord]) -> float:
    """Calculates the average physical progress of all actions in the plan."""
    if not records:
        return 0.0
    total = sum(r.progress_percentage for r in records)
    return round(total / len(records), 1)
