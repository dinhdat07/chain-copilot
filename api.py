from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from actions.executor import apply_plan
from core.enums import ApprovalStatus, EventType, Mode, PlanStatus
from core.memory import SQLiteStore
from core.models import Event
from core.state import clone_state, load_initial_state, state_summary, utc_now
from orchestrator.graph import build_graph
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


@app.get("/api/v1/state")
def get_state() -> dict:
    return {"summary": state_summary(STATE), "state": STATE.model_dump(mode="json")}


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
    return {
        "summary": state_summary(STATE),
        "latest_plan": STATE.latest_plan.model_dump(mode="json") if STATE.latest_plan else None,
        "decision_id": _current_decision_id(),
    }


@app.post("/api/v1/scenarios/run")
def run_scenario(request: ScenarioRequest) -> dict:
    global STATE
    if request.scenario_name not in list_scenarios():
        raise HTTPException(status_code=404, detail="unknown scenario")
    STATE = RUNNER.run(STATE, request.scenario_name, seed=request.seed)
    return {
        "summary": state_summary(STATE),
        "latest_plan": STATE.latest_plan.model_dump(mode="json") if STATE.latest_plan else None,
        "scenario_history_count": len(STATE.scenario_history),
    }


@app.post("/api/v1/decisions/{decision_id}/approve")
def approve_decision(decision_id: str, request: ApprovalRequest) -> dict:
    global STATE
    if not STATE.pending_plan or not STATE.decision_logs:
        raise HTTPException(status_code=404, detail="no pending decision")
    current_decision = STATE.decision_logs[-1]
    if current_decision.decision_id != decision_id:
        raise HTTPException(status_code=404, detail="decision not found")

    if request.approve:
        STATE.pending_plan.status = PlanStatus.APPROVED
        STATE = apply_plan(STATE, STATE.pending_plan)
        if STATE.decision_logs:
            STATE.decision_logs[-1].approval_status = ApprovalStatus.APPROVED
        STATE.mode = Mode.CRISIS if STATE.active_events else Mode.NORMAL
    else:
        STATE.pending_plan.status = PlanStatus.REJECTED
        current_decision.approval_status = ApprovalStatus.REJECTED
        STATE.pending_plan = None
        if STATE.decision_logs:
            STATE.decision_logs[-1].approval_status = ApprovalStatus.REJECTED
        STATE.mode = Mode.NORMAL
    STORE.save_state(STATE)
    STORE.save_decision_log(STATE.decision_logs[-1] if STATE.decision_logs else current_decision)
    return {
        "decision_id": decision_id,
        "approved": request.approve,
        "summary": state_summary(STATE),
    }


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
