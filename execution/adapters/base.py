from __future__ import annotations

from abc import ABC, abstractmethod

from execution.models import DispatchResult, ExecutionRecord


class BaseAdapter(ABC):
    """
    Abstract contract every system adapter must implement.
    Concrete implementations: ERPAdapter, WMSAdapter, TMSAdapter.
    """

    @abstractmethod
    def dispatch(self, record: ExecutionRecord, dry_run: bool) -> DispatchResult:
        """
        Send the action payload to the target system.
        - dry_run=True  → validate-only, no side effects.
        - dry_run=False → commit the transaction.
        Must be idempotent: check get_receipt() first.
        """
        ...

    @abstractmethod
    def rollback(self, record: ExecutionRecord) -> DispatchResult:
        """
        Attempt to compensate / undo a previously dispatched action.
        In real supply-chain contexts this is often advisory only.
        """
        ...

    @abstractmethod
    def get_receipt(self, idempotency_key: str) -> DispatchResult | None:
        """
        Return the cached receipt if this key was already processed.
        Returns None if the key is unseen.
        """
        ...
