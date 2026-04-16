from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core.enums import EventType
from core.models import Event
from core.state import load_initial_state


def test_initial_state_loads() -> None:
    state = load_initial_state()
    assert state.inventory
    assert state.kpis.total_cost > 0


def test_event_rejects_backwards_detection_time() -> None:
    with pytest.raises(ValidationError):
        Event(
            event_id="evt_bad",
            type=EventType.SUPPLIER_DELAY,
            source="test",
            severity=0.5,
            entity_ids=["SUP_BN"],
            occurred_at=datetime(2026, 4, 8, tzinfo=timezone.utc),
            detected_at=datetime(2026, 4, 7, tzinfo=timezone.utc),
            payload={},
            dedupe_key="evt_bad",
        )
