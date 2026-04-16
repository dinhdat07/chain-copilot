from pathlib import Path

from fastapi.testclient import TestClient

import api
from core.memory import SQLiteStore
from core.state import load_initial_state
from orchestrator.graph import build_graph
from simulation.runner import ScenarioRunner


def _client(tmp_path: Path) -> TestClient:
    store = SQLiteStore(tmp_path / "chaincopilot-run-history.db")
    api.replace_runtime(
        store=store,
        state=load_initial_state(),
        graph=build_graph(),
        runner=ScenarioRunner(store=store),
    )
    return TestClient(api.app)


def test_runs_list_returns_latest_first(tmp_path: Path) -> None:
    client = _client(tmp_path)

    first = client.post(
        "/api/v1/events/ingest",
        json={"event_class": "command", "event_type": "plan_requested", "source": "api"},
    )
    assert first.status_code == 200
    second = client.post(
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
    assert second.status_code == 200

    response = client.get("/api/v1/runs?limit=2")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 2
    assert len(payload["items"]) == 2
    assert payload["items"][0]["run_id"] == second.json()["run_id"]
    assert payload["items"][1]["run_id"] == first.json()["run_id"]


def test_run_state_returns_historical_snapshot(tmp_path: Path) -> None:
    client = _client(tmp_path)

    daily = client.post(
        "/api/v1/events/ingest",
        json={"event_class": "command", "event_type": "plan_requested", "source": "api"},
    )
    assert daily.status_code == 200

    crisis = client.post(
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
    assert crisis.status_code == 200

    daily_state = client.get(f"/api/v1/runs/{daily.json()['run_id']}/state")
    assert daily_state.status_code == 200
    daily_payload = daily_state.json()
    assert daily_payload["run"]["run_id"] == daily.json()["run_id"]
    assert daily_payload["state"]["summary"]["mode"] == "normal"
    assert daily_payload["state"]["latest_trace"]["run_id"] == daily.json()["run_id"]

    crisis_state = client.get(f"/api/v1/runs/{crisis.json()['run_id']}/state")
    assert crisis_state.status_code == 200
    crisis_payload = crisis_state.json()
    assert crisis_payload["run"]["run_id"] == crisis.json()["run_id"]
    assert crisis_payload["state"]["summary"]["mode"] in {"crisis", "approval"}
    assert crisis_payload["state"]["latest_trace"]["run_id"] == crisis.json()["run_id"]
    assert crisis_payload["state"]["summary"]["pending_approval"] is not None


def test_missing_run_history_returns_404(tmp_path: Path) -> None:
    client = _client(tmp_path)

    run_response = client.get("/api/v1/runs/run_missing")
    assert run_response.status_code == 404

    trace_response = client.get("/api/v1/runs/run_missing/trace")
    assert trace_response.status_code == 404

    state_response = client.get("/api/v1/runs/run_missing/state")
    assert state_response.status_code == 404
