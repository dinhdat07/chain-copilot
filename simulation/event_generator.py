from __future__ import annotations

import random

from core.enums import EventType
from core.models import Event
from core.state import utc_now


def random_event(seed: int = 7) -> Event:
    random.seed(seed)
    event_type = random.choice(
        [EventType.SUPPLIER_DELAY, EventType.DEMAND_SPIKE, EventType.ROUTE_BLOCKAGE]
    )
    now = utc_now()
    return Event(
        event_id=f"evt_random_{seed}",
        type=event_type,
        source="generator",
        severity=round(random.uniform(0.4, 0.9), 2),
        entity_ids=["SKU_1"],
        occurred_at=now,
        detected_at=now,
        payload={"seed": seed},
        dedupe_key=f"evt_random_{seed}",
    )
