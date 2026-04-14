from __future__ import annotations

import random
from datetime import datetime, timezone
from uuid import uuid4

from execution.adapters.base import BaseAdapter
from execution.models import DispatchResult, ExecutionRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _StubAdapter(BaseAdapter):
    """
    Simulated adapter shared by ERP / WMS / TMS stubs.
    Behaviour:
      dry_run  → always success, no side-effects.
      commit   → 85% success | 8% permanent failure | 7% transient failure
    Receipt cache ensures idempotency per key.
    """

    def __init__(self, system_name: str, failure_rate: float = 0.15, transient_ratio: float = 0.07):
        self._system = system_name
        self._failure_rate = failure_rate      # total failure probability
        self._transient_ratio = transient_ratio  # fraction that is retryable
        self._receipt_cache: dict[str, DispatchResult] = {}

    # ------------------------------------------------------------------
    def get_receipt(self, idempotency_key: str) -> DispatchResult | None:
        return self._receipt_cache.get(idempotency_key)

    # ------------------------------------------------------------------
    def dispatch(self, record: ExecutionRecord, dry_run: bool) -> DispatchResult:
        # --- Idempotency check first ---
        cached = self.get_receipt(record.idempotency_key)
        if cached is not None:
            return cached

        if dry_run:
            result = DispatchResult(
                success=True,
                receipt={
                    "ref_id": f"{self._system}-DRY-{uuid4().hex[:6].upper()}",
                    "status": "DRY_RUN_OK",
                    "system": self._system,
                    "timestamp": _now_iso(),
                },
            )
            # dry-run results are NOT cached (not idempotent by design)
            return result

        # --- Commit mode: simulate failure distribution ---
        roll = random.random()
        if roll < self._transient_ratio:
            result = DispatchResult(
                success=False,
                error_code="NETWORK_TIMEOUT",
                error_message=f"{self._system}: connection timed out. Safe to retry.",
                is_retryable=True,
            )
        elif roll < self._failure_rate:
            result = DispatchResult(
                success=False,
                error_code="BUSINESS_RULE_VIOLATED",
                error_message=f"{self._system}: action rejected by downstream policy. Do not retry.",
                is_retryable=False,
            )
        else:
            result = DispatchResult(
                success=True,
                receipt={
                    "ref_id": f"{self._system}-{uuid4().hex[:8].upper()}",
                    "status": "COMMITTED",
                    "system": self._system,
                    "action_id": record.action_id,
                    "timestamp": _now_iso(),
                },
            )

        # Cache successful (and permanent-failed) results to enforce idempotency
        if result.success or not result.is_retryable:
            self._receipt_cache[record.idempotency_key] = result

        return result

    # ------------------------------------------------------------------
    def rollback(self, record: ExecutionRecord) -> DispatchResult:
        return DispatchResult(
            success=True,
            receipt={
                "ref_id": f"{self._system}-ROLLBACK-{uuid4().hex[:6].upper()}",
                "status": "COMPENSATION_LOGGED",
                "system": self._system,
                "original_action_id": record.action_id,
                "note": "Manual intervention may still be required.",
                "timestamp": _now_iso(),
            },
        )


# ---------------------------------------------------------------------------
# Public stub instances — one per target system
# ---------------------------------------------------------------------------

class ERPAdapter(_StubAdapter):
    def __init__(self) -> None:
        super().__init__("ERP")


class WMSAdapter(_StubAdapter):
    def __init__(self) -> None:
        super().__init__("WMS")


class TMSAdapter(_StubAdapter):
    def __init__(self) -> None:
        super().__init__("TMS")
