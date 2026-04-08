from core.enums import Mode
from core.models import Event, SystemState


NORMAL_WEIGHTS = {"alpha": 0.35, "beta": 0.40, "gamma": 0.15, "delta": 0.10}
CRISIS_WEIGHTS = {"alpha": 0.30, "beta": 0.10, "gamma": 0.25, "delta": 0.35}


def get_weights(mode: Mode) -> dict[str, float]:
    return CRISIS_WEIGHTS if mode == Mode.CRISIS else NORMAL_WEIGHTS


def select_mode(state: SystemState, event: Event | None) -> Mode:
    if event is None:
        return Mode.NORMAL
    if event.severity >= 0.65:
        return Mode.CRISIS
    if state.kpis.service_level < 0.93:
        return Mode.CRISIS
    if state.kpis.stockout_risk > 0.30:
        return Mode.CRISIS
    if event.type.value == "compound":
        return Mode.CRISIS
    return Mode.NORMAL
