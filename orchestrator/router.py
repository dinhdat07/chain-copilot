from __future__ import annotations

from typing import Mapping, cast

from core.enums import Mode
from core.models import SystemState


def _state_from_graph(graph_state: Mapping[str, object]) -> SystemState:
    return cast(SystemState, graph_state["state"])


def route_after_risk(graph_state: Mapping[str, object]) -> str:
    state = _state_from_graph(graph_state)
    if state.pending_plan is not None or state.mode == Mode.APPROVAL:
        return "approval"
    if state.mode == Mode.CRISIS:
        return "crisis"
    return "normal"


def route_after_planner(graph_state: Mapping[str, object]) -> str:
    return "critic"


def route_after_critic(graph_state: Mapping[str, object]) -> str:
    state = _state_from_graph(graph_state)
    if state.latest_plan and state.latest_plan.approval_required:
        return "approval"
    return "execution"
