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
    assert payload["execution"]["status"] == "approved"
    assert [item["status"] for item in payload["execution"]["status_history"]] == [
        "planned",
        "approval_pending",
        "approved",
    ]

    execution = client.get(f"/api/v1/execution/{original_execution_id}")
    assert execution.status_code == 200
    assert execution.json()["item"]["status"] == "approved"


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


def test_dry_run_dispatch_is_preview_only(tmp_path: Path) -> None:
    client = _client(tmp_path)

    daily = client.post("/api/v1/plan/daily")
    assert daily.status_code == 200
    plan = daily.json()["latest_plan"]
    assert plan is not None
    plan_id = plan["plan_id"]

    first = client.post(f"/api/v1/execution/{plan_id}/dispatch", json={"mode": "dry_run"})
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["dispatch_mode"] == "dry_run"
    assert first_payload["records"]

    history = client.get("/api/v1/execution")
    assert history.status_code == 200
    history_payload = history.json()
    assert all(item["plan_id"] != plan_id for item in history_payload["items"])


def test_commit_dispatch_is_idempotent_for_same_plan_and_mode(tmp_path: Path) -> None:
    client = _client(tmp_path)

    daily = client.post("/api/v1/plan/daily")
    assert daily.status_code == 200
    plan = daily.json()["latest_plan"]
    assert plan is not None
    plan_id = plan["plan_id"]

    first = client.post(f"/api/v1/execution/{plan_id}/dispatch", json={"mode": "commit"})
    assert first.status_code == 200
    first_payload = first.json()
    first_ids = {item["execution_id"] for item in first_payload["records"]}
    assert first_ids

    second = client.post(f"/api/v1/execution/{plan_id}/dispatch", json={"mode": "commit"})
    assert second.status_code == 200
    second_payload = second.json()
    second_ids = {item["execution_id"] for item in second_payload["records"]}

    assert second_ids == first_ids
    assert second_payload["dispatch_mode"] == "commit"
    assert second_payload["plan_execution_status"] == first_payload["plan_execution_status"]
