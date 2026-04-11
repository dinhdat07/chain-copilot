from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.enums import EventType
from core.memory import SQLiteStore
from core.models import Event
from core.state import clone_state, load_initial_state, state_summary, utc_now
from orchestrator.graph import build_graph
from orchestrator.service import (
    PendingApprovalError,
    approve_pending_plan,
    request_safer_plan,
    reset_runtime,
    run_daily_plan,
)
from simulation.runner import ScenarioRunner
from simulation.scenarios import get_scenario_events, list_scenarios


class ScenarioRequest(BaseModel):
    scenario_name: str
    seed: int = 7


class ApprovalRequest(BaseModel):
    approve: bool = True


class WhatIfRequest(BaseModel):
    scenario_name: str
    seed: int = 7


class EventRequest(BaseModel):
    type: EventType
    severity: float = Field(ge=0.0, le=1.0)
    source: str = "api"
    entity_ids: list[str] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)


STORE = SQLiteStore()
STATE = load_initial_state()
GRAPH = build_graph()
RUNNER = ScenarioRunner(store=STORE)


def _current_decision_id() -> str | None:
    if not STATE.decision_logs:
        return None
    return STATE.decision_logs[-1].decision_id


app = FastAPI(title="ChainCopilot API", version="0.1.0")


def _response_payload() -> dict:
    return {
        "summary": state_summary(STATE),
        "latest_plan": STATE.latest_plan.model_dump(mode="json") if STATE.latest_plan else None,
        "pending_plan": STATE.pending_plan.model_dump(mode="json") if STATE.pending_plan else None,
        "decision_id": _current_decision_id(),
    }


@app.get("/api/v1/state")
def get_state() -> dict:
    return {"summary": state_summary(STATE), "state": STATE.model_dump(mode="json")}


@app.post("/api/v1/reset")
def reset_state() -> dict:
    global STATE, GRAPH, RUNNER
    STATE = reset_runtime(STORE)
    GRAPH = build_graph()
    RUNNER = ScenarioRunner(store=STORE)
    return {"summary": state_summary(STATE), "state": STATE.model_dump(mode="json")}


@app.post("/api/v1/plan/daily")
def daily_plan() -> dict:
    global STATE
    try:
        STATE = run_daily_plan(STATE, STORE, graph=GRAPH)
    except PendingApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _response_payload()




@app.post("/api/v1/events")
def ingest_event(request: EventRequest) -> dict:
    global STATE
    event = Event(
        event_id=f"evt_api_{request.type.value}_{int(utc_now().timestamp())}",
        type=request.type,
        source=request.source,
        severity=request.severity,
        entity_ids=request.entity_ids,
        occurred_at=utc_now(),
        detected_at=utc_now(),
        payload=request.payload,
        dedupe_key=f"{request.type.value}:{request.entity_ids}:{request.payload}",
    )
    STATE = GRAPH.invoke(STATE, event)
    STORE.save_state(STATE)
    if STATE.decision_logs:
        STORE.save_decision_log(STATE.decision_logs[-1])
    return _response_payload()


@app.post("/api/v1/scenarios/run")
def run_scenario(request: ScenarioRequest) -> dict:
    global STATE
    if request.scenario_name not in list_scenarios():
        raise HTTPException(status_code=404, detail="unknown scenario")
    try:
        STATE = RUNNER.run(STATE, request.scenario_name, seed=request.seed)
    except PendingApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    payload = _response_payload()
    payload["scenario_history_count"] = len(STATE.scenario_history)
    return payload


@app.post("/api/v1/decisions/{decision_id}/approve")
def approve_decision(decision_id: str, request: ApprovalRequest) -> dict:
    global STATE
    try:
        STATE = approve_pending_plan(STATE, STORE, decision_id, request.approve)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = _response_payload()
    payload["approved"] = request.approve
    return payload


@app.post("/api/v1/decisions/{decision_id}/safer-plan")
def safer_plan(decision_id: str) -> dict:
    global STATE
    try:
        STATE = request_safer_plan(STATE, STORE, decision_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _response_payload()


@app.get("/api/v1/decision-logs")
def decision_logs() -> dict:
    return {"items": STORE.list_decision_logs()}


@app.post("/api/v1/what-if")
def what_if(request: WhatIfRequest) -> dict:
    if request.scenario_name not in list_scenarios():
        raise HTTPException(status_code=404, detail="unknown scenario")
    simulated = clone_state(STATE)
    for event in get_scenario_events(request.scenario_name):
        simulated = GRAPH.invoke(simulated, event)
    return {
        "scenario_name": request.scenario_name,
        "summary": state_summary(simulated),
        "latest_plan": simulated.latest_plan.model_dump(mode="json") if simulated.latest_plan else None,
    }
