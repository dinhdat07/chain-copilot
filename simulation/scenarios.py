from __future__ import annotations

import json
from pathlib import Path

from core.enums import EventType
from core.models import Event
from core.state import utc_now


def build_event(
    *,
    event_id: str,
    event_type: EventType,
    severity: float,
    payload: dict,
    entity_ids: list[str],
) -> Event:
    now = utc_now()
    return Event(
        event_id=event_id,
        type=event_type,
        source="scenario_runner",
        severity=severity,
        entity_ids=entity_ids,
        occurred_at=now,
        detected_at=now,
        payload=payload,
        dedupe_key=event_id,
    )


def get_scenario_events(name: str) -> list[Event]:
    mapping = {
        "supplier_delay": [
            build_event(
                event_id="evt_supplier_delay",
                event_type=EventType.SUPPLIER_DELAY,
                severity=0.80,
                payload={"supplier_id": "SUP_BN", "sku": "SKU_001", "delay_hours": 48},
                entity_ids=["SUP_BN", "SKU_001"],
            )
        ],
        "demand_spike": [
            build_event(
                event_id="evt_demand_spike",
                event_type=EventType.DEMAND_SPIKE,
                severity=0.70,
                payload={"sku": "SKU_024", "multiplier": 2.2},
                entity_ids=["SKU_024"],
            )
        ],
        "route_blockage": [
            build_event(
                event_id="evt_route_blockage",
                event_type=EventType.ROUTE_BLOCKAGE,
                severity=0.78,
                payload={"route_id": "R_BN_HN_MAIN", "reason": "flooding"},
                entity_ids=["R_BN_HN_MAIN"],
            )
        ],
        "compound_disruption": [
            build_event(
                event_id="evt_compound_delay",
                event_type=EventType.COMPOUND,
                severity=0.92,
                payload={
                    "supplier_id": "SUP_BN",
                    "route_id": "R_BN_HN_MAIN",
                    "sku": "SKU_001",
                },
                entity_ids=["SUP_BN", "R_BN_HN_MAIN", "SKU_001"],
            ),
            build_event(
                event_id="evt_compound_spike",
                event_type=EventType.DEMAND_SPIKE,
                severity=0.75,
                payload={"sku": "SKU_024", "multiplier": 1.9},
                entity_ids=["SKU_024"],
            ),
        ],
    }
    return mapping[name]


def list_scenarios() -> list[str]:
    return ["supplier_delay", "demand_spike", "route_blockage", "compound_disruption"]


def load_scenarios_json(path: Path | None = None) -> dict:
    file_path = path or (
        Path(__file__).resolve().parent.parent / "data" / "scenarios.json"
    )
    return json.loads(file_path.read_text(encoding="utf-8"))
