from __future__ import annotations

from typing import Mapping, cast

from core.enums import Mode, EventType
from core.models import SystemState


def _state_from_graph(graph_state: Mapping[str, object]) -> SystemState:
    return cast(SystemState, graph_state["state"])


def route_after_risk(graph_state: Mapping[str, object]) -> str:
    state = _state_from_graph(graph_state)
    if state.pending_plan is not None or state.mode == Mode.APPROVAL:
        return "approval"

    event_type = state.active_events[-1].type if state.active_events else None

    if event_type in [EventType.ROUTE_BLOCKAGE, EventType.COMPOUND]:
        return "logistics"
    elif event_type == EventType.SUPPLIER_DELAY:
        return "supplier"
    elif event_type == EventType.DEMAND_SPIKE:
        return "demand"

    return "planner"


def route_after_planner(graph_state: Mapping[str, object]) -> str:
    return "critic"


def route_after_critic(graph_state: Mapping[str, object]) -> str:
    state = _state_from_graph(graph_state)
    if state.latest_plan and state.latest_plan.approval_required:
        return "approval"
    return "execution"
