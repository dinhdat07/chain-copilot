from core.models import KPIState


def metric_summary(before: KPIState, after: KPIState) -> dict[str, float]:
    return {
        "service_level_delta": round(after.service_level - before.service_level, 4),
        "cost_delta": round(after.total_cost - before.total_cost, 2),
        "recovery_speed_delta": round(after.recovery_speed - before.recovery_speed, 4),
        "stockout_risk_delta": round(after.stockout_risk - before.stockout_risk, 4),
        "decision_latency_ms": round(after.decision_latency_ms, 2),
    }
