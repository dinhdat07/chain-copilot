from pathlib import Path

from fastapi.testclient import TestClient

import api
from core.memory import SQLiteStore
from core.state import load_initial_state
from orchestrator.graph import build_graph
from simulation.runner import ScenarioRunner


def _client(tmp_path: Path) -> tuple[TestClient, SQLiteStore]:
    store = SQLiteStore(tmp_path / "chaincopilot-foundation.db")
    api.replace_runtime(
        store=store,
        state=load_initial_state(),
        graph=build_graph(),
        runner=ScenarioRunner(store=store),
    )
    return TestClient(api.app), store


def test_event_ingest_persists_run_trace_and_execution(tmp_path: Path) -> None:
    client, store = _client(tmp_path)

    response = client.post(
        "/api/v1/events/ingest",
        json={
            "event_class": "domain",
            "event_type": "supplier_delay",
            "source": "api",
            "severity": 0.9,
            "entity_ids": ["SKU_001", "SUP_BN"],
            "payload": {"supplier_id": "SUP_BN", "sku": "SKU_001", "delay_hours": 48},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["run_id"] is not None
    assert payload["execution_id"] is not None
    assert payload["event"]["event_class"] == "domain"
    assert store.get_event_envelope(payload["event"]["event_id"]) is not None

    run_response = client.get(f"/api/v1/runs/{payload['run_id']}")
    assert run_response.status_code == 200
    run_payload = run_response.json()["item"]
    assert run_payload["run_type"] == "event_response"
    assert run_payload["execution_id"] == payload["execution_id"]
    assert run_payload["selected_plan_summary"] is not None

    trace_response = client.get(f"/api/v1/runs/{payload['run_id']}/trace")
    assert trace_response.status_code == 200
    trace_payload = trace_response.json()["item"]
    assert trace_payload["run_id"] == payload["run_id"]
    assert trace_payload["trace_id"] is not None
    assert trace_payload["steps"]
    assert trace_payload["steps"][0]["step_id"] is not None
    assert trace_payload["steps"][0]["sequence"] == 1

    execution_response = client.get(f"/api/v1/execution/{payload['execution_id']}")
    assert execution_response.status_code == 200
    execution_payload = execution_response.json()["item"]
    assert execution_payload["run_id"] == payload["run_id"]
    assert execution_payload["dispatch_mode"] == "simulation"
    assert execution_payload["status"] == "approval_pending"


def test_command_event_creates_unique_run_and_exposes_llm_fallback(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    first = client.post(
        "/api/v1/events/ingest",
        json={
            "event_class": "command",
            "event_type": "plan_requested",
            "source": "api",
        },
    )
    assert first.status_code == 200
    second = client.post(
        "/api/v1/events/ingest",
        json={
            "event_class": "command",
            "event_type": "plan_requested",
            "source": "api",
        },
    )
    assert second.status_code == 200

    first_run_id = first.json()["run_id"]
    second_run_id = second.json()["run_id"]
    assert first_run_id is not None
    assert second_run_id is not None
    assert first_run_id != second_run_id

    run_response = client.get(f"/api/v1/runs/{second_run_id}")
    assert run_response.status_code == 200
    run_payload = run_response.json()["item"]
    assert run_payload["run_type"] == "daily_cycle"
    assert run_payload["llm_fallback_used"] is True
    assert run_payload["llm_fallback_reason"] == "llm_disabled"


def test_system_event_is_logged_without_creating_run(tmp_path: Path) -> None:
    client, store = _client(tmp_path)

    response = client.post(
        "/api/v1/events/ingest",
        json={
            "event_class": "system",
            "event_type": "reflection_completed",
            "source": "api",
            "payload": {"note_id": "note_1"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["run_id"] is None
    assert payload["execution_id"] is None
    assert store.get_event_envelope(payload["event"]["event_id"]) is not None
