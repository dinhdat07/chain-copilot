from core.enums import Mode
from policies.modes import get_weights


def normalize_cost(total_cost: float, baseline_cost: float) -> float:
    if baseline_cost <= 0:
        return min(total_cost / 1000.0, 1.0)
    ratio = total_cost / baseline_cost
    return max(0.0, min(ratio, 2.0)) / 2.0


def compute_score(
    *,
    service_level: float,
    total_cost: float,
    disruption_risk: float,
    recovery_speed: float,
    mode: Mode,
    baseline_cost: float,
) -> tuple[float, dict[str, float]]:
    weights = get_weights(mode)
    normalized_cost = normalize_cost(total_cost, baseline_cost)
    breakdown = {
        "service_level": round(weights["alpha"] * service_level, 6),
        "total_cost": round(-weights["beta"] * normalized_cost, 6),
        "disruption_risk": round(-weights["gamma"] * disruption_risk, 6),
        "recovery_speed": round(weights["delta"] * recovery_speed, 6),
    }
    return round(sum(breakdown.values()), 6), breakdown
