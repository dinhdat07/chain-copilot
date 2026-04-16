from core.enums import Mode
from core.models import Event, KPIState, Plan


def approval_required(
    plan: Plan,
    before_kpis: KPIState,
    after_kpis: KPIState,
    event: Event | None,
) -> tuple[bool, str]:
    if plan.mode == Mode.NORMAL:
        return False, ""
    if event and event.severity >= 0.75:
        return True, "Event severity exceeds approval threshold"
    if event and event.severity >= 0.65 and len(plan.actions) >= 3:
        return True, "Disruption response package exceeds automatic execution threshold"
    if before_kpis.total_cost > 0:
        cost_increase = (after_kpis.total_cost - before_kpis.total_cost) / before_kpis.total_cost
        if cost_increase > 0.15:
            return True, "Projected cost increase exceeds 15%"
    if before_kpis.service_level - after_kpis.service_level > 0.03:
        return True, "Projected service level drop exceeds 3 points"
    changed_suppliers = sum(1 for action in plan.actions if action.action_type.value == "switch_supplier")
    changed_routes = sum(1 for action in plan.actions if action.action_type.value == "reroute")
    if changed_suppliers and changed_routes:
        return True, "Plan changes supplier and route in the same cycle"
    return False, ""
