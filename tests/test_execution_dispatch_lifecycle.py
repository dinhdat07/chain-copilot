from pathlib import Path

from fastapi.testclient import TestClient

import api
from core.memory import SQLiteStore
from core.state import load_initial_state
from orchestrator.graph import build_graph
from simulation.runner import ScenarioRunner


def _client(tmp_path: Path) -> TestClient:
    store = SQLiteStore(tmp_path / "chaincopilot-execution.db")
    api.replace_runtime(
        store=store,
        state=load_initial_state(),
        graph=build_graph(),
        runner=ScenarioRunner(store=store),
    )
    return TestClient(api.app)


def test_daily_plan_creates_applied_execution_history(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/v1/events/ingest",
        json={"event_class": "command", "event_type": "plan_requested", "source": "api"},
    )
    assert response.status_code == 200
    execution_id = response.json()["execution_id"]
    assert execution_id is not None

    execution = client.get(f"/api/v1/execution/{execution_id}")
    assert execution.status_code == 200
    payload = execution.json()["item"]
    assert payload["status"] == "applied"
    assert [item["status"] for item in payload["status_history"]] == ["planned", "applied"]
    assert payload["receipts"]


def test_approve_updates_existing_execution_record(tmp_path: Path) -> None:
    client = _client(tmp_path)

    scenario = client.post("/api/v1/scenarios/run", json={"scenario_name": "supplier_delay"})
    assert scenario.status_code == 200
    pending_run = client.get("/api/v1/runs?limit=1").json()["items"][0]
    original_execution_id = pending_run["execution_id"]
    decision_id = scenario.json()["decision_id"]
    assert original_execution_id is not None
    assert decision_id is not None

    response = client.post(f"/api/v1/approvals/{decision_id}", json={"action": "approve"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["execution"] is not None
    assert payload["execution"]["execution_id"] == original_execution_id
    assert payload["execution"]["status"] == "applied"
    assert [item["status"] for item in payload["execution"]["status_history"]] == [
        "planned",
        "approval_pending",
        "approved",
        "applied",
    ]

    execution = client.get(f"/api/v1/execution/{original_execution_id}")
    assert execution.status_code == 200
    assert execution.json()["item"]["status"] == "applied"


def test_reject_cancels_existing_execution_record(tmp_path: Path) -> None:
    client = _client(tmp_path)

    scenario = client.post("/api/v1/scenarios/run", json={"scenario_name": "supplier_delay"})
    assert scenario.status_code == 200
    pending_run = client.get("/api/v1/runs?limit=1").json()["items"][0]
    original_execution_id = pending_run["execution_id"]
    decision_id = scenario.json()["decision_id"]
    assert original_execution_id is not None
    assert decision_id is not None

    response = client.post(f"/api/v1/approvals/{decision_id}", json={"action": "reject"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["execution"] is not None
    assert payload["execution"]["execution_id"] == original_execution_id
    assert payload["execution"]["status"] == "cancelled"
    assert payload["execution"]["failure_reason"] == "operator rejected the pending execution"


def test_safer_plan_cancels_old_execution_and_creates_new_one(tmp_path: Path) -> None:
    client = _client(tmp_path)

    scenario = client.post("/api/v1/scenarios/run", json={"scenario_name": "compound_disruption"})
    assert scenario.status_code == 200
    pending_run = client.get("/api/v1/runs?limit=1").json()["items"][0]
    original_execution_id = pending_run["execution_id"]
    decision_id = scenario.json()["decision_id"]
    assert original_execution_id is not None
    assert decision_id is not None

    response = client.post(f"/api/v1/approvals/{decision_id}", json={"action": "safer_plan"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["execution"] is not None
    new_execution_id = payload["execution"]["execution_id"]
    assert new_execution_id != original_execution_id

    original_execution = client.get(f"/api/v1/execution/{original_execution_id}")
    assert original_execution.status_code == 200
    assert original_execution.json()["item"]["status"] == "cancelled"

    replacement_execution = client.get(f"/api/v1/execution/{new_execution_id}")
    assert replacement_execution.status_code == 200
    assert replacement_execution.json()["item"]["status"] in {"approval_pending", "applied"}
