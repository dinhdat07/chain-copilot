from pathlib import Path

from fastapi.testclient import TestClient

import api
from agents.planner import PlannerAgent
from core.enums import ActionType, EventType, Mode
from core.memory import SQLiteStore
from core.models import Action, Event
from core.state import load_initial_state, utc_now
from orchestrator.graph import build_graph
from policies.constraints import evaluate_plan_constraints, mode_rationale
from simulation.runner import ScenarioRunner


def _event(event_type: EventType, severity: float, payload: dict, entity_ids: list[str]) -> Event:
    return Event(
        event_id=f"evt_{event_type.value}",
        type=event_type,
        source="test",
        severity=severity,
        entity_ids=entity_ids,
        occurred_at=utc_now(),
        detected_at=utc_now(),
        payload=payload,
        dedupe_key=f"{event_type.value}:{entity_ids}:{payload}",
    )


def _client(tmp_path: Path) -> TestClient:
    store = SQLiteStore(tmp_path / "chaincopilot-policy.db")
    api.replace_runtime(
        store=store,
        state=load_initial_state(),
        graph=build_graph(),
        runner=ScenarioRunner(store=store),
    )
    return TestClient(api.app)


def test_constraints_detect_blocked_route_and_capacity_overflow() -> None:
    state = load_initial_state()
    event = _event(
        EventType.ROUTE_BLOCKAGE,
        0.78,
        {"route_id": "R1", "reason": "flooding"},
        ["R1"],
    )
    violations = evaluate_plan_constraints(
        state=state,
        event=event,
        actions=[
            Action(
                action_id="act_reroute_blocked",
                action_type=ActionType.REROUTE,
                target_id="SKU_1",
                parameters={"route_id": "R1"},
            ),
            Action(
                action_id="act_reorder_overflow",
                action_type=ActionType.REORDER,
                target_id="SKU_1",
                parameters={"quantity": 10_000},
            ),
        ],
    )

    assert {item.code for item in violations} == {"route_blocked", "warehouse_capacity_exceeded"}


def test_planner_excludes_infeasible_candidates_before_selection() -> None:
    state = load_initial_state()
    state.mode = Mode.CRISIS
    event = _event(
        EventType.ROUTE_BLOCKAGE,
        0.78,
        {"route_id": "R1", "reason": "flooding"},
        ["R1"],
    )
    state.candidate_actions = [
        Action(
            action_id="act_reroute_blocked",
            action_type=ActionType.REROUTE,
            target_id="SKU_1",
            parameters={"route_id": "R1"},
            estimated_cost_delta=8.0,
            estimated_service_delta=0.05,
            estimated_risk_delta=-0.1,
            estimated_recovery_hours=6.0,
            reason="reroute SKU_1 through blocked route",
            priority=0.9,
        ),
        Action(
            action_id="act_no_op_policy",
            action_type=ActionType.NO_OP,
            target_id="system",
            reason="hold current plan",
            priority=0.1,
        ),
    ]

    PlannerAgent().run(state, event)

    log = state.decision_logs[-1]
    assert any(not item.feasible for item in log.candidate_evaluations)
    blocked_eval = next(
        item
        for item in log.candidate_evaluations
        if any(violation.code == "route_blocked" for violation in item.violations)
    )
    assert blocked_eval.feasible is False
    assert state.latest_plan is not None
    assert state.latest_plan.feasible is True
    assert "excluding" in log.selection_reason


def test_policy_fields_surface_through_api(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/v1/events/ingest",
        json={
            "event_class": "domain",
            "event_type": "supplier_delay",
            "source": "api",
            "severity": 0.8,
            "entity_ids": ["SUP_A", "SKU_1"],
            "payload": {"supplier_id": "SUP_A", "sku": "SKU_1", "delay_hours": 48},
        },
    )
    assert response.status_code == 200
    decision_id = client.get("/api/v1/decision-logs").json()["items"][0]["decision_id"]

    plan_response = client.get("/api/v1/plans/latest")
    assert plan_response.status_code == 200
    plan_payload = plan_response.json()["item"]
    assert plan_payload["mode_rationale"]
    assert isinstance(plan_payload["feasible"], bool)
    assert "violations" in plan_payload

    decision_response = client.get(f"/api/v1/decision-logs/{decision_id}")
    assert decision_response.status_code == 200
    decision_payload = decision_response.json()["item"]
    assert decision_payload["mode_rationale"]
    assert all("feasible" in item for item in decision_payload["candidate_evaluations"])


def test_mode_rationale_explains_crisis_switch() -> None:
    state = load_initial_state()
    event = _event(
        EventType.COMPOUND,
        0.92,
        {"supplier_id": "SUP_A", "route_id": "R1", "sku": "SKU_1"},
        ["SUP_A", "R1", "SKU_1"],
    )
    assert "compound disruption" in mode_rationale(state, event)
