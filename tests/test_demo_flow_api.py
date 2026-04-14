from pathlib import Path

from fastapi.testclient import TestClient

import api
from core.enums import ApprovalStatus, PlanStatus
from core.memory import SQLiteStore
from core.state import load_initial_state
from orchestrator.graph import build_graph
from simulation.runner import ScenarioRunner


def _reset_api_state(tmp_path: Path) -> TestClient:
    store = SQLiteStore(tmp_path / "chaincopilot-test.db")
    api.replace_runtime(
        store=store,
        state=load_initial_state(),
        graph=build_graph(),
        runner=ScenarioRunner(store=store),
    )
    return TestClient(api.app)


def test_daily_plan_endpoint_returns_normal_mode_plan(tmp_path: Path) -> None:
    client = _reset_api_state(tmp_path)

    response = client.post("/api/v1/plan/daily")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["mode"] == "normal"
    assert payload["latest_plan"] is not None
    assert payload["latest_plan"]["mode"] == "normal"
    assert payload["latest_plan"]["status"] == PlanStatus.APPLIED.value
    assert payload["pending_plan"] is None


def test_approval_endpoint_applies_pending_plan(tmp_path: Path) -> None:
    client = _reset_api_state(tmp_path)

    scenario_response = client.post("/api/v1/scenarios/run", json={"scenario_name": "supplier_delay"})
    assert scenario_response.status_code == 200
    pending_decision_id = scenario_response.json()["decision_id"]
    assert pending_decision_id is not None

    response = client.post(
        f"/api/v1/decisions/{pending_decision_id}/approve",
        json={"approve": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pending_plan"] is None
    assert payload["latest_plan"] is not None
    assert payload["latest_plan"]["status"] == PlanStatus.APPROVED.value
    assert api.RUNTIME.state.decision_logs[-1].approval_status == ApprovalStatus.APPROVED


def test_safer_plan_endpoint_creates_new_pending_plan(tmp_path: Path) -> None:
    client = _reset_api_state(tmp_path)

    scenario_response = client.post("/api/v1/scenarios/run", json={"scenario_name": "compound_disruption"})
    assert scenario_response.status_code == 200
    initial_payload = scenario_response.json()
    initial_decision_id = initial_payload["decision_id"]
    initial_plan_id = initial_payload["pending_plan"]["plan_id"]

    response = client.post(f"/api/v1/decisions/{initial_decision_id}/safer-plan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["pending_plan"] is not None
    assert payload["pending_plan"]["plan_id"] != initial_plan_id
    assert payload["decision_id"] != initial_decision_id
    assert len(payload["pending_plan"]["actions"]) <= 1
    assert api.RUNTIME.state.decision_logs[-2].approval_status == ApprovalStatus.REJECTED
    assert api.RUNTIME.state.decision_logs[-1].approval_status in {
        ApprovalStatus.PENDING,
        ApprovalStatus.AUTO_APPLIED,
    }


def test_daily_plan_endpoint_is_blocked_while_approval_is_pending(tmp_path: Path) -> None:
    client = _reset_api_state(tmp_path)

    scenario_response = client.post("/api/v1/scenarios/run", json={"scenario_name": "supplier_delay"})
    assert scenario_response.status_code == 200

    response = client.post("/api/v1/plan/daily")

    assert response.status_code == 409
    assert "pending approval" in response.json()["message"]


def test_scenario_endpoint_is_blocked_while_approval_is_pending(tmp_path: Path) -> None:
    client = _reset_api_state(tmp_path)

    scenario_response = client.post("/api/v1/scenarios/run", json={"scenario_name": "compound_disruption"})
    assert scenario_response.status_code == 200

    response = client.post("/api/v1/scenarios/run", json={"scenario_name": "route_blockage"})

    assert response.status_code == 409
    assert "pending approval" in response.json()["message"]
