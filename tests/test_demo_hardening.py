import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

import api
from core.enums import Mode
from core.memory import SQLiteStore
from core.state import load_initial_state
from orchestrator.graph import build_graph
from simulation.runner import ScenarioRunner


def _reset_api_state(tmp_path: Path) -> TestClient:
    api.STORE = SQLiteStore(tmp_path / "chaincopilot-hardening.db")
    api.STATE = load_initial_state()
    api.GRAPH = build_graph()
    api.RUNNER = ScenarioRunner(store=api.STORE)
    return TestClient(api.app)


def test_reset_endpoint_clears_persisted_state(tmp_path: Path) -> None:
    client = _reset_api_state(tmp_path)
    scenario_response = client.post("/api/v1/scenarios/run", json={"scenario_name": "route_blockage"})
    assert scenario_response.status_code == 200

    with sqlite3.connect(api.STORE.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM state_snapshots").fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM decision_logs").fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM scenario_runs").fetchone()[0] > 0

    response = client.post("/api/v1/reset")

    assert response.status_code == 200
    assert api.STATE.decision_logs == []
    assert api.STATE.scenario_history == []
    assert api.STATE.pending_plan is None
    assert api.STATE.mode == Mode.NORMAL

    with sqlite3.connect(api.STORE.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM state_snapshots").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM decision_logs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM scenario_runs").fetchone()[0] == 0


def test_rejecting_pending_plan_keeps_crisis_mode_when_events_remain(tmp_path: Path) -> None:
    client = _reset_api_state(tmp_path)
    scenario_response = client.post("/api/v1/scenarios/run", json={"scenario_name": "supplier_delay"})
    decision_id = scenario_response.json()["decision_id"]

    response = client.post(
        f"/api/v1/decisions/{decision_id}/approve",
        json={"approve": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["mode"] == Mode.CRISIS.value
    assert payload["pending_plan"] is None
