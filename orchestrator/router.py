from core.enums import Mode
from core.models import SystemState


def route_after_risk(state: SystemState) -> str:
    if state.pending_plan is not None or state.mode == Mode.APPROVAL:
        return "approval"
    if state.mode == Mode.CRISIS:
        return "crisis"
    return "normal"
