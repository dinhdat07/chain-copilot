from pathlib import Path

from fastapi.testclient import TestClient

import api
from core.memory import SQLiteStore
from core.state import load_initial_state
from orchestrator.graph import build_graph
from simulation.runner import ScenarioRunner


def _client(tmp_path: Path) -> TestClient:
    store = SQLiteStore(tmp_path / "chaincopilot-backend-api.db")
    api.replace_runtime(
        store=store,
        state=load_initial_state(),
        graph=build_graph(),
        runner=ScenarioRunner(store=store),
    )
    return TestClient(api.app)


def test_control_tower_summary_contract(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/v1/control-tower/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "normal"
    assert payload["kpis"]["service_level"] >= 0.0
    assert isinstance(payload["alerts"], list)
    assert payload["pending_approval"] is None


def test_inventory_and_supplier_endpoints_return_typed_items(tmp_path: Path) -> None:
    client = _client(tmp_path)

    inventory_response = client.get("/api/v1/inventory")
    supplier_response = client.get("/api/v1/suppliers")

    assert inventory_response.status_code == 200
    inventory_payload = inventory_response.json()
    assert inventory_payload["total"] > 0
    assert {"sku", "status", "preferred_supplier_id"} <= set(inventory_payload["items"][0].keys())

    assert supplier_response.status_code == 200
    supplier_payload = supplier_response.json()
    assert supplier_payload["total"] > 0
    assert {"supplier_id", "reliability", "tradeoff"} <= set(supplier_payload["items"][0].keys())


def test_trace_and_plan_endpoints_expose_latest_daily_plan(tmp_path: Path) -> None:
    client = _client(tmp_path)

    run_response = client.post("/api/v1/plan/daily")
    assert run_response.status_code == 200

    plan_response = client.get("/api/v1/plans/latest")
    trace_response = client.get("/api/v1/trace/latest")

    assert plan_response.status_code == 200
    plan_payload = plan_response.json()["item"]
    assert plan_payload is not None
    assert plan_payload["mode"] == "normal"
    assert len(plan_payload["actions"]) >= 1

    assert trace_response.status_code == 200
    trace_payload = trace_response.json()["item"]
    assert trace_payload["trace_id"] is not None
    assert trace_payload["status"] == "completed"
    assert trace_payload["current_branch"] == "normal"
    assert trace_payload["terminal_stage"] == "execution"
    assert [step["agent"] for step in trace_payload["steps"]][:2] == ["risk", "demand"]
    assert trace_payload["route_decisions"][0]["from_node"] == "risk"
    assert trace_payload["route_decisions"][-1]["to_node"] == "execution"
    assert trace_payload["latest_plan"]["plan_id"] == plan_payload["plan_id"]


def test_pending_approval_and_unified_approval_command(tmp_path: Path) -> None:
    client = _client(tmp_path)

    scenario_response = client.post("/api/v1/scenarios/run", json={"scenario_name": "supplier_delay"})
    assert scenario_response.status_code == 200
    decision_id = scenario_response.json()["decision_id"]
    assert decision_id is not None

    pending_response = client.get("/api/v1/approvals/pending")
    assert pending_response.status_code == 200
    pending_payload = pending_response.json()["item"]
    assert pending_payload is not None
    assert pending_payload["decision_id"] == decision_id
    assert pending_payload["plan"]["approval_required"] is True
    assert pending_payload["allowed_actions"] == ["approve", "reject", "safer_plan"]
    assert pending_payload["blocking_operations"] == ["plan_daily", "scenario_run"]
    assert pending_payload["candidate_count"] == 3

    detail_response = client.get(f"/api/v1/approvals/{decision_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["item"]
    assert detail_payload["is_pending"] is True
    assert detail_payload["approval_status"] == "pending"
    assert detail_payload["allowed_actions"] == ["approve", "reject", "safer_plan"]

    trace_response = client.get("/api/v1/trace/latest")
    assert trace_response.status_code == 200
    trace_payload = trace_response.json()["item"]
    assert trace_payload["current_branch"] == "crisis"
    assert trace_payload["terminal_stage"] == "approval"
    assert trace_payload["approval_pending"] is True
    assert trace_payload["execution_status"] == "pending_approval"
    assert trace_payload["route_decisions"][-1]["to_node"] == "approval"

    approve_response = client.post(
        f"/api/v1/approvals/{decision_id}",
        json={"action": "approve"},
    )
    assert approve_response.status_code == 200
    approve_payload = approve_response.json()
    assert approve_payload["action"] == "approve"
    assert approve_payload["approval_status"] == "approved"
    assert approve_payload["pending_approval"] is None
    assert approve_payload["latest_plan"]["approval_status"] == "approved"
    assert approve_payload["latest_trace"]["execution_status"] == "approved_pending_dispatch"


def test_reject_and_safer_plan_transitions_are_explicit(tmp_path: Path) -> None:
    client = _client(tmp_path)

    scenario_response = client.post("/api/v1/scenarios/run", json={"scenario_name": "compound_disruption"})
    assert scenario_response.status_code == 200
    decision_id = scenario_response.json()["decision_id"]
    assert decision_id is not None

    safer_response = client.post(
        f"/api/v1/approvals/{decision_id}",
        json={"action": "safer_plan"},
    )
    assert safer_response.status_code == 200
    safer_payload = safer_response.json()
    assert safer_payload["action"] == "safer_plan"
    assert safer_payload["pending_approval"] is not None or safer_payload["approval_status"] == "auto_applied"
    assert safer_payload["latest_trace"]["execution_status"] in {"safer_plan_pending", "safer_plan_auto_applied"}

    latest_decision_id = safer_payload["decision_id"]
    if safer_payload["pending_approval"] is not None:
        reject_response = client.post(
            f"/api/v1/approvals/{latest_decision_id}",
            json={"action": "reject"},
        )
        assert reject_response.status_code == 200
        reject_payload = reject_response.json()
        assert reject_payload["action"] == "reject"
        assert reject_payload["approval_status"] == "rejected"
        assert reject_payload["pending_approval"] is None
        assert reject_payload["latest_trace"]["execution_status"] == "rejected"
        assert reject_payload["summary"]["pending_approval"] is None


def test_operator_can_select_alternative_then_request_single_safer_plan(tmp_path: Path) -> None:
    client = _client(tmp_path)

    scenario_response = client.post("/api/v1/scenarios/run", json={"scenario_name": "demand_spike"})
    assert scenario_response.status_code == 200
    decision_id = scenario_response.json()["decision_id"]
    assert decision_id is not None

    trace_response = client.get("/api/v1/trace/latest")
    assert trace_response.status_code == 200
    trace_payload = trace_response.json()["item"]
    selected_strategy = trace_payload["selected_strategy"]
    alternatives = [
        item for item in trace_payload["candidate_evaluations"]
        if item["strategy_label"] != selected_strategy
    ]
    assert alternatives
    chosen = alternatives[0]["strategy_label"]

    select_response = client.post(
        f"/api/v1/approvals/{decision_id}/select-alternative",
        json={"strategy_label": chosen},
    )
    assert select_response.status_code == 200
    select_payload = select_response.json()
    assert select_payload["action"] == "select_alternative"
    assert select_payload["pending_approval"] is not None
    assert select_payload["pending_approval"]["plan"]["strategy_label"] == chosen

    replacement_decision_id = select_payload["decision_id"]
    detail_response = client.get(f"/api/v1/approvals/{replacement_decision_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["item"]
    assert detail_payload["plan"]["strategy_label"] == chosen
    assert len(detail_payload["plan"]["actions"]) >= 1

    safer_response = client.post(
        f"/api/v1/approvals/{replacement_decision_id}",
        json={"action": "safer_plan"},
    )
    assert safer_response.status_code == 200
    safer_payload = safer_response.json()
    assert safer_payload["pending_approval"] is not None
    assert safer_payload["pending_approval"]["plan"]["strategy_label"] == "safer_alternative"
    assert safer_payload["pending_approval"]["allowed_actions"] == ["approve", "reject"]

    second_safer = client.post(
        f"/api/v1/approvals/{safer_payload['decision_id']}",
        json={"action": "safer_plan"},
    )
    assert second_safer.status_code == 409
    assert "once per approval cycle" in second_safer.json()["message"]


def test_crisis_trace_records_critic_and_candidate_metadata(tmp_path: Path) -> None:
    client = _client(tmp_path)

    scenario_response = client.post("/api/v1/scenarios/run", json={"scenario_name": "route_blockage"})
    assert scenario_response.status_code == 200

    trace_response = client.get("/api/v1/trace/latest")
    assert trace_response.status_code == 200
    trace_payload = trace_response.json()["item"]
    assert trace_payload["candidate_count"] == 3
    assert trace_payload["selected_strategy"] in {"cost_first", "balanced", "resilience_first"}
    assert "critic" in [step["agent"] for step in trace_payload["steps"]]
    critic_step = next(step for step in trace_payload["steps"] if step["agent"] == "critic")
    assert critic_step["status"] == "completed"
    assert "finding_count" in critic_step["output_snapshot"]


def test_decision_detail_and_reflections_contract(tmp_path: Path) -> None:
    client = _client(tmp_path)

    scenario_response = client.post("/api/v1/scenarios/run", json={"scenario_name": "route_blockage"})
    assert scenario_response.status_code == 200
    decision_id = scenario_response.json()["decision_id"]
    if scenario_response.json()["pending_plan"] is not None:
        approval_response = client.post(
            f"/api/v1/approvals/{decision_id}",
            json={"action": "approve"},
        )
        assert approval_response.status_code == 200

    logs_response = client.get("/api/v1/decision-logs")
    assert logs_response.status_code == 200
    log_items = logs_response.json()["items"]
    assert len(log_items) >= 1
    latest_decision_id = log_items[0]["decision_id"]

    detail_response = client.get(f"/api/v1/decision-logs/{latest_decision_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["item"]
    assert {"before_kpis", "after_kpis", "candidate_evaluations"} <= set(detail_payload.keys())

    reflections_response = client.get("/api/v1/reflections")
    assert reflections_response.status_code == 200
    reflections_payload = reflections_response.json()
    assert "items" in reflections_payload
    assert "scenarios" in reflections_payload


def test_persisted_decision_detail_survives_runtime_replacement(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "chaincopilot-backend-api.db")
    api.replace_runtime(
        store=store,
        state=load_initial_state(),
        graph=build_graph(),
        runner=ScenarioRunner(store=store),
    )
    client = TestClient(api.app)

    scenario_response = client.post("/api/v1/scenarios/run", json={"scenario_name": "supplier_delay"})
    assert scenario_response.status_code == 200
    decision_id = scenario_response.json()["decision_id"]
    assert decision_id is not None

    api.replace_runtime(
        store=store,
        state=load_initial_state(),
        graph=build_graph(),
        runner=ScenarioRunner(store=store),
    )
    restarted_client = TestClient(api.app)

    detail_response = restarted_client.get(f"/api/v1/decision-logs/{decision_id}")
    assert detail_response.status_code == 200
    payload = detail_response.json()["item"]
    assert payload["decision_id"] == decision_id
