from __future__ import annotations

import time
import threading
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from core.enums import ActionType, ExecutionStatus
from core.models import Action, Plan
from execution.adapters.base import BaseAdapter
from execution.adapters.stubs import ERPAdapter, TMSAdapter, WMSAdapter
from execution.models import (
    DispatchResult,
    ExecutionRecord,
    PlanDispatchSummary,
    make_idempotency_key,
    utc_now,
)
from execution.state_machine import (
    InvalidTransitionError,
    compute_overall_progress,
    compute_plan_execution_status,
    transition,
)


# ---------------------------------------------------------------------------
# Routing table: ActionType → target system + adapter class
# ---------------------------------------------------------------------------

_ROUTING: dict[ActionType, tuple[str, type[BaseAdapter]]] = {
    ActionType.REORDER:         ("ERP", ERPAdapter),
    ActionType.SWITCH_SUPPLIER: ("ERP", ERPAdapter),
    ActionType.REBALANCE:       ("WMS", WMSAdapter),
    ActionType.REROUTE:         ("TMS", TMSAdapter),
}

_MAX_RETRIES = 3
_BACKOFF_SECONDS = [1, 2, 4]   # Exponential backoff steps


def _build_payload(action: Action) -> dict:
    return {
        "action_type": action.action_type.value,
        "target_id": action.target_id,
        "parameters": action.parameters,
        "estimated_cost_delta": action.estimated_cost_delta,
        "estimated_recovery_hours": action.estimated_recovery_hours,
    }


def _compensation_hint(record: ExecutionRecord) -> str:
    """Provides human-readable suggestions when a physical action fails."""
    hints = {
        "reorder":         f"Manually place reorder for {record.payload.get('target_id')} in ERP.",
        "switch_supplier": f"Contact procurement to manually switch supplier for {record.payload.get('target_id')}.",
        "reroute":         f"Maintain current route; escalate TMS alert for {record.payload.get('target_id')}.",
        "rebalance":       f"Trigger manual warehouse rebalance via WMS portal.",
    }
    return hints.get(record.action_type, "Manual intervention required.")


# ---------------------------------------------------------------------------
# ActionDispatchService
# ---------------------------------------------------------------------------

class ActionDispatchService:
    """
    Central coordinator responsible for:
    1. Building ExecutionRecords for each action in a Plan.
    2. Routing records to the appropriate adapter (ERP / WMS / TMS).
    3. Mandatory Idempotency, Retry logic, and State Machine transitions.
    4. Aggregating action-level results into a PlanDispatchSummary.
    """

    def __init__(self) -> None:
        # Adapter pool — one instance per system (persistent receipt cache)
        self._adapters: dict[str, BaseAdapter] = {
            "ERP": ERPAdapter(),
            "WMS": WMSAdapter(),
            "TMS": TMSAdapter(),
        }
        # State Locking Mechanism to prevent race conditions during concurrent dispatch
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def dispatch_plan(
        self,
        plan: Plan,
        mode: Literal["dry_run", "commit"] = "dry_run",
    ) -> PlanDispatchSummary:
        """
        Executes all actions within a plan.
        Returns a summary containing per-action ExecutionRecords and aggregate progress.
        """
        approval_ts = utc_now().isoformat()
        records: list[ExecutionRecord] = []
        compensation_hints: list[str] = []

        for action in plan.actions:
            if action.action_type == ActionType.NO_OP:
                continue

            record = self._build_record(plan.plan_id, action, approval_ts)
            record = self._run_action(record, mode=mode)
            records.append(record)

            # If the action failed or was rolled back, append a manual recovery hint
            if record.status in {ExecutionStatus.FAILED, ExecutionStatus.ROLLED_BACK}:
                compensation_hints.append(_compensation_hint(record))

        plan_status = compute_plan_execution_status(records)
        overall_progress = compute_overall_progress(records)

        return PlanDispatchSummary(
            plan_id=plan.plan_id,
            dispatch_mode=mode,
            plan_execution_status=plan_status,
            overall_progress=overall_progress,
            records=records,
            compensation_hints=compensation_hints,
        )

    def get_record(self, execution_id: str, records: list[ExecutionRecord]) -> ExecutionRecord | None:
        """Helper to find a specific record by its ID."""
        return next((r for r in records if r.execution_id == execution_id), None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_record(self, plan_id: str, action: Action, approval_ts: str) -> ExecutionRecord:
        target_system, _ = _ROUTING.get(action.action_type, ("ERP", ERPAdapter))
        idem_key = make_idempotency_key(plan_id, action.action_id, approval_ts)
        return ExecutionRecord(
            execution_id=f"exec_{uuid4().hex[:8]}",
            plan_id=plan_id,
            action_id=action.action_id,
            action_type=action.action_type.value,
            target_system=target_system,
            payload=_build_payload(action),
            idempotency_key=idem_key,
            status=ExecutionStatus.PLANNED,
        )

    def _run_action(
        self,
        record: ExecutionRecord,
        mode: Literal["dry_run", "commit"],
    ) -> ExecutionRecord:
        """Drives a single record through the state machine — Thread-Safe Execution."""
        dry_run = mode == "dry_run"
        adapter = self._adapters[record.target_system]

        with self._lock:  # State Locking starts here
            # PLANNED → APPROVED 
            transition(record, ExecutionStatus.APPROVED)

            # APPROVED → DISPATCHED
            transition(record, ExecutionStatus.DISPATCHED)
            record.dispatched_at = utc_now()

            result = self._call_with_retry(adapter, record, dry_run)

            if result.success:
                transition(record, ExecutionStatus.APPLIED)
                record.receipt = result.receipt
                record.applied_at = utc_now()
                
                # Calculate physical ETA based on action lead time
                duration_hours = record.payload.get("estimated_recovery_hours", 0.0)
                from datetime import timedelta
                record.estimated_completion_at = record.applied_at + timedelta(hours=duration_hours)
                
                # Initial progress set to 10% upon digital success
                record.progress_percentage = 10.0 
            else:
                record.failure_reason = result.error_message
                record.is_retryable = result.is_retryable
                try:
                    transition(record, ExecutionStatus.FAILED)
                except InvalidTransitionError:
                    pass  

                if not result.is_retryable:
                    # Attempt advisory compensation/rollback
                    rollback_result = adapter.rollback(record)
                    if rollback_result.success:
                        try:
                            transition(record, ExecutionStatus.ROLLED_BACK)
                            record.receipt = rollback_result.receipt
                        except InvalidTransitionError:
                            pass
        # Lock released automatically after the 'with' block

        return record

    def _call_with_retry(
        self,
        adapter: BaseAdapter,
        record: ExecutionRecord,
        dry_run: bool,
    ) -> DispatchResult:
        """Retry transient errors up to _MAX_RETRIES times with exponential backoff."""
        for attempt in range(_MAX_RETRIES):
            result = adapter.dispatch(record, dry_run=dry_run)
            if result.success or not result.is_retryable:
                return result
            # Transient error — wait and retry
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_SECONDS[attempt])
        return result   # return last failed result after exhausting retries
