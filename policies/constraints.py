from __future__ import annotations

from abc import ABC, abstractmethod

from core.enums import ActionType, ConstraintViolationCode, EventType, Mode
from core.models import (
    ConstraintViolation as Violation,
    Event,
    Plan,
    SupplierRecord,
    SystemState,
)


# ---------------------------------------------------------------------------
# Mode rationale
# ---------------------------------------------------------------------------

def mode_rationale(state: SystemState, event: Event | None) -> str:
    if event is None:
        return "normal mode selected because no disruption event is active"
    if event.type == EventType.COMPOUND:
        return "crisis mode selected because a compound disruption affects multiple domains"
    if event.severity >= 0.65:
        return f"crisis mode selected because event severity {event.severity:.2f} exceeds the crisis threshold"
    if state.kpis.service_level < 0.93:
        return (
            f"crisis mode selected because service level {state.kpis.service_level:.2%} "
            "fell below the resilience threshold"
        )
    if state.kpis.stockout_risk > 0.30:
        return (
            f"crisis mode selected because stockout risk {state.kpis.stockout_risk:.2%} "
            "exceeds the resilience threshold"
        )
    if state.mode == Mode.NORMAL:
        return "normal mode selected because disruption severity and service risk remain within operating limits"
    return "current mode retained based on active disruption context"


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

def _blocked_routes(state: SystemState, event: Event | None) -> set[str]:
    blocked = {
        item.payload.get("route_id")
        for item in state.active_events
        if item.type in {EventType.ROUTE_BLOCKAGE, EventType.COMPOUND}
    }
    if event is not None and event.type in {EventType.ROUTE_BLOCKAGE, EventType.COMPOUND}:
        blocked.add(event.payload.get("route_id"))
    return {item for item in blocked if item}


def _delayed_suppliers(state: SystemState, event: Event | None) -> set[str]:
    delayed = {
        item.payload.get("supplier_id")
        for item in state.active_events
        if item.type in {EventType.SUPPLIER_DELAY, EventType.COMPOUND}
    }
    if event is not None and event.type in {EventType.SUPPLIER_DELAY, EventType.COMPOUND}:
        delayed.add(event.payload.get("supplier_id"))
    return {item for item in delayed if item}


def _warehouse_stock(state: SystemState, warehouse_id: str) -> int:
    return sum(
        item.on_hand + item.incoming_qty
        for item in state.inventory.values()
        if item.warehouse_id == warehouse_id
    )


def _reorder_additions_per_warehouse(plan: Plan, state: SystemState) -> dict[str, int]:
    totals: dict[str, int] = {}
    for action in plan.actions:
        if action.action_type != ActionType.REORDER:
            continue
        item = state.inventory.get(action.target_id)
        if item is None:
            continue
        qty = int(action.parameters.get("quantity", 0))
        totals[item.warehouse_id] = totals.get(item.warehouse_id, 0) + qty
    return totals


def _supplier_record(
    state: SystemState,
    supplier_id: str,
    sku: str | None = None,
) -> SupplierRecord | None:
    if sku is not None:
        supplier = state.suppliers.get(f"{supplier_id}_{sku}")
        if supplier is not None:
            return supplier
    supplier = state.suppliers.get(supplier_id)
    if supplier is not None:
        return supplier
    for record in state.suppliers.values():
        if record.supplier_id == supplier_id and (sku is None or record.sku == sku):
            return record
    return None


# ---------------------------------------------------------------------------
# Base rule
# ---------------------------------------------------------------------------

class BaseRule(ABC):
    """Abstract base class for all logistics constraint rules."""

    @property
    @abstractmethod
    def code(self) -> ConstraintViolationCode:
        """Unique violation code for this rule."""

    @property
    def priority(self) -> int:
        """Evaluation priority; lower value runs first."""
        return 100

    @property
    def is_critical(self) -> bool:
        """When True, the engine short-circuits on the first violation."""
        return False

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        """Return violations found by this rule."""


# ---------------------------------------------------------------------------
# Hard constraint rules
# ---------------------------------------------------------------------------

class SupplierExistenceRule(BaseRule):
    code = ConstraintViolationCode.SUPPLIER_NOT_FOUND
    priority = 10
    is_critical = True

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type != ActionType.SWITCH_SUPPLIER:
                continue
            supplier_id = action.parameters.get("supplier_id") or action.target_id
            if _supplier_record(state, supplier_id, action.target_id) is None:
                violations.append(Violation(
                    code=self.code,
                    message=f"supplier {supplier_id} does not exist",
                ))
        return violations


class SupplierStatusRule(BaseRule):
    """Rejects plans that reference an inactive or delayed supplier."""
    code = ConstraintViolationCode.SUPPLIER_BLOCKED
    priority = 20

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type != ActionType.SWITCH_SUPPLIER:
                continue
            supplier_id = action.parameters.get("supplier_id") or action.target_id
            supplier = _supplier_record(state, supplier_id, action.target_id)
            if supplier is None:
                continue
            if supplier.status != "active":
                violations.append(Violation(
                    code=self.code,
                    message=f"supplier {supplier_id} is not active (status: {supplier.status})",
                ))
        return violations


class SupplierSkuMatchRule(BaseRule):
    """Ensures the chosen supplier actually supplies the target SKU."""
    code = ConstraintViolationCode.SUPPLIER_NOT_FOUND
    priority = 25

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type != ActionType.SWITCH_SUPPLIER:
                continue
            supplier_id = action.parameters.get("supplier_id") or action.target_id
            supplier = _supplier_record(state, supplier_id, action.target_id)
            if supplier is None:
                continue
            if supplier.sku != action.target_id:
                violations.append(Violation(
                    code=self.code,
                    message=f"supplier {supplier_id} does not supply SKU {action.target_id}",
                ))
        return violations


class SupplierDelayRule(BaseRule):
    """Blocks switch to a supplier that is currently delayed."""
    code = ConstraintViolationCode.SUPPLIER_BLOCKED
    priority = 30

    def __init__(self, event: Event | None = None) -> None:
        self._event = event

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        delayed = _delayed_suppliers(state, self._event)
        violations = []
        for action in plan.actions:
            if action.action_type != ActionType.SWITCH_SUPPLIER:
                continue
            supplier_id = action.parameters.get("supplier_id") or action.target_id
            if supplier_id in delayed:
                violations.append(Violation(
                    code=self.code,
                    message=f"supplier {supplier_id} is currently delayed by an active disruption",
                ))
        return violations


class RouteExistenceRule(BaseRule):
    code = ConstraintViolationCode.ROUTE_NOT_FOUND
    priority = 10
    is_critical = True

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type != ActionType.REROUTE:
                continue
            route_id = action.parameters.get("route_id") or action.target_id
            if route_id not in state.routes:
                violations.append(Violation(
                    code=self.code,
                    message=f"route {route_id} does not exist",
                ))
        return violations


class RouteBlockedRule(BaseRule):
    code = ConstraintViolationCode.ROUTE_BLOCKED
    priority = 20

    def __init__(self, event: Event | None = None) -> None:
        self._event = event

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        blocked = _blocked_routes(state, self._event)
        violations = []
        for action in plan.actions:
            if action.action_type != ActionType.REROUTE:
                continue
            route_id = action.parameters.get("route_id") or action.target_id
            route = state.routes.get(route_id)
            if route is None:
                continue
            if route.status == "blocked" or route_id in blocked:
                violations.append(Violation(
                    code=self.code,
                    message=f"route {route_id} is blocked by an active disruption",
                ))
        return violations


class ReorderQuantityRule(BaseRule):
    """Rejects reorder actions with a zero or negative quantity."""
    code = ConstraintViolationCode.MOQ_NOT_MET
    priority = 15

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type != ActionType.REORDER:
                continue
            if state.inventory.get(action.target_id) is None:
                violations.append(Violation(
                    code=ConstraintViolationCode.INVENTORY_SHORTAGE,
                    message=f"inventory target {action.target_id} does not exist",
                ))
                continue
            qty = int(action.parameters.get("quantity", 0) or 0)
            if qty <= 0:
                violations.append(Violation(
                    code=self.code,
                    message=f"reorder quantity must be greater than zero for {action.target_id}",
                ))
        return violations


class WarehouseCapacityRule(BaseRule):
    """Blocks plans where the aggregate reorder volume exceeds warehouse capacity."""
    code = ConstraintViolationCode.CAPACITY_EXCEEDED
    priority = 40

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        violations = []
        additions = _reorder_additions_per_warehouse(plan, state)
        for wh_id, added in additions.items():
            wh = state.warehouses.get(wh_id)
            if wh is None:
                continue
            current = _warehouse_stock(state, wh_id)
            projected = current + added
            if projected > wh.capacity:
                violations.append(Violation(
                    code=self.code,
                    message=(
                        f"warehouse {wh_id} capacity {wh.capacity} would be exceeded "
                        f"by projected stock {projected}"
                    ),
                ))
        return violations


class RebalanceRule(BaseRule):
    """Validates rebalance actions for quantity and availability."""
    code = ConstraintViolationCode.INVENTORY_SHORTAGE
    priority = 20

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type != ActionType.REBALANCE:
                continue
            item = state.inventory.get(action.target_id)
            qty = int(action.parameters.get("quantity", 0) or 0)
            if item is None:
                violations.append(Violation(
                    code=self.code,
                    message=f"inventory target {action.target_id} does not exist",
                ))
                continue
            if qty <= 0:
                violations.append(Violation(
                    code=self.code,
                    message=f"rebalance quantity must be greater than zero for {action.target_id}",
                ))
                continue
            available = item.on_hand + item.incoming_qty
            if qty > available:
                violations.append(Violation(
                    code=self.code,
                    message=(
                        f"rebalance quantity {qty} exceeds available inventory {available} "
                        f"for {action.target_id}"
                    ),
                ))
        return violations


class MOQRule(BaseRule):
    """Enforces minimum order quantity requirements passed via action parameters."""
    code = ConstraintViolationCode.MOQ_NOT_MET
    priority = 35

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type != ActionType.REORDER:
                continue
            moq = int(action.parameters.get("moq_required", 0))
            qty = int(action.parameters.get("quantity", 0))
            if moq and qty < moq:
                violations.append(Violation(
                    code=self.code,
                    message=f"reorder quantity {qty} is below MOQ {moq} for {action.target_id}",
                ))
        return violations


class SupplierCapacityRule(BaseRule):
    """Rejects orders that exceed the supplier's declared capacity."""
    code = ConstraintViolationCode.SUPPLIER_CAPACITY_EXCEEDED
    priority = 40

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type not in {ActionType.REORDER, ActionType.SWITCH_SUPPLIER}:
                continue
            item = state.inventory.get(action.target_id)
            if item is None:
                continue
            qty = int(action.parameters.get("quantity", 0)) or item.forecast_qty
            supplier_id = action.parameters.get("supplier_id") or item.preferred_supplier_id
            supplier = _supplier_record(state, supplier_id, item.sku)
            if supplier and qty > supplier.capacity:
                violations.append(Violation(
                    code=self.code,
                    message=(
                        f"order quantity {qty} exceeds supplier {supplier_id} "
                        f"capacity of {supplier.capacity}"
                    ),
                ))
        return violations


class SLARule(BaseRule):
    """Flags routes whose transit time exceeds the action's max allowed ETA."""
    code = ConstraintViolationCode.SLA_VIOLATED
    priority = 45

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type not in {ActionType.REORDER, ActionType.REROUTE}:
                continue
            route_id = action.parameters.get("route_id")
            if not route_id:
                item = state.inventory.get(action.target_id)
                route_id = item.preferred_route_id if item else None
            if not route_id:
                continue
            route = state.routes.get(route_id)
            if route is None:
                continue
            max_eta = int(action.parameters.get("max_eta_days", 999))
            if route.transit_days > max_eta:
                violations.append(Violation(
                    code=self.code,
                    message=(
                        f"route {route_id} transit {route.transit_days}d "
                        f"exceeds max allowed {max_eta}d"
                    ),
                ))
        return violations


# ---------------------------------------------------------------------------
# Soft constraint rules (warnings)
# ---------------------------------------------------------------------------

class BackupSupplierRule(BaseRule):
    """Warning: switching to a non-primary supplier adds overhead."""
    code = ConstraintViolationCode.SUPPLIER_BLOCKED
    priority = 10

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        warnings = []
        for action in plan.actions:
            if action.action_type != ActionType.SWITCH_SUPPLIER:
                continue
            supplier_id = action.parameters.get("supplier_id") or action.target_id
            supplier = _supplier_record(state, supplier_id, action.target_id)
            if supplier and not supplier.is_primary:
                warnings.append(Violation(
                    code=self.code,
                    message=f"switching to backup supplier {supplier_id} increases operational overhead",
                ))
        return warnings


class CostToleranceRule(BaseRule):
    """Warning: action cost delta is unusually high."""
    code = ConstraintViolationCode.SLA_VIOLATED
    priority = 20

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        warnings = []
        for action in plan.actions:
            if action.estimated_cost_delta > 5_000:
                warnings.append(Violation(
                    code=self.code,
                    message=(
                        f"action {action.action_id} has high estimated cost delta "
                        f"(${action.estimated_cost_delta:,.0f})"
                    ),
                ))
        return warnings


class LowReliabilityRule(BaseRule):
    """Warning: selected supplier has reliability below the acceptable threshold."""
    code = ConstraintViolationCode.RELIABILITY_LOW
    priority = 30

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        warnings = []
        for action in plan.actions:
            supplier_id = action.parameters.get("supplier_id")
            if not supplier_id:
                continue
            supplier = _supplier_record(state, supplier_id, action.target_id)
            if supplier and supplier.reliability < 0.85:
                warnings.append(Violation(
                    code=self.code,
                    message=f"supplier {supplier_id} has low reliability ({supplier.reliability:.0%})",
                ))
        return warnings


class HighRouteRiskRule(BaseRule):
    """Warning: chosen route has an elevated risk score."""
    code = ConstraintViolationCode.RISK_HIGH
    priority = 30

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        warnings = []
        for action in plan.actions:
            if action.action_type != ActionType.REROUTE:
                continue
            route_id = action.parameters.get("route_id") or action.target_id
            route = state.routes.get(route_id)
            if route and route.risk_score > 0.4:
                warnings.append(Violation(
                    code=self.code,
                    message=f"route {route_id} has a high risk score ({route.risk_score:.2f})",
                ))
        return warnings


class WarehouseUtilizationRule(BaseRule):
    """Warning: reorder plans push warehouse utilization close to its limit."""
    code = ConstraintViolationCode.CAPACITY_EXCEEDED
    priority = 40

    def evaluate(self, plan: Plan, state: SystemState) -> list[Violation]:
        warnings = []
        additions = _reorder_additions_per_warehouse(plan, state)
        for wh_id, added in additions.items():
            wh = state.warehouses.get(wh_id)
            if wh is None or wh.capacity == 0:
                continue
            current = _warehouse_stock(state, wh_id)
            utilization = (current + added) / wh.capacity
            if 0.85 <= utilization <= 1.0:
                warnings.append(Violation(
                    code=self.code,
                    message=f"warehouse {wh_id} will reach {utilization:.0%} utilization after reorder",
                ))
        return warnings


# ---------------------------------------------------------------------------
# Constraint engine
# ---------------------------------------------------------------------------

class ConstraintEngine:
    """Runs an ordered list of rules and accumulates violations."""

    def __init__(self, rules: list[BaseRule]) -> None:
        self.rules = sorted(rules, key=lambda r: r.priority)

    def evaluate(self, plan: Plan, state: SystemState) -> tuple[bool, list[Violation]]:
        all_violations: list[Violation] = []
        for rule in self.rules:
            found = rule.evaluate(plan, state)
            if found:
                all_violations.extend(found)
                if rule.is_critical:
                    return False, all_violations
        return len(all_violations) == 0, all_violations


# ---------------------------------------------------------------------------
# Pre-built engines
# ---------------------------------------------------------------------------

def _make_hard_engine(event: Event | None = None) -> ConstraintEngine:
    return ConstraintEngine([
        SupplierExistenceRule(),
        SupplierStatusRule(),
        SupplierSkuMatchRule(),
        SupplierDelayRule(event),
        RouteExistenceRule(),
        RouteBlockedRule(event),
        ReorderQuantityRule(),
        RebalanceRule(),
        MOQRule(),
        WarehouseCapacityRule(),
        SupplierCapacityRule(),
        SLARule(),
    ])


_SOFT_ENGINE = ConstraintEngine([
    BackupSupplierRule(),
    CostToleranceRule(),
    LowReliabilityRule(),
    HighRouteRiskRule(),
    WarehouseUtilizationRule(),
])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_hard_constraints(
    plan: Plan,
    state: SystemState,
    event: Event | None = None,
) -> tuple[bool, list[Violation]]:
    """Return (feasible, violations) for all hard constraints."""
    return _make_hard_engine(event).evaluate(plan, state)


def evaluate_soft_constraints(
    plan: Plan,
    state: SystemState,
) -> list[Violation]:
    """Return soft-constraint warnings for a plan."""
    _, warnings = _SOFT_ENGINE.evaluate(plan, state)
    for w in warnings:
        w.severity = "soft"
    return warnings


def evaluate_plan_constraints(
    *,
    state: SystemState,
    event: Event | None,
    actions: list,
) -> list[Violation]:
    """Compatibility shim used by planner/_evaluate_candidate.

    Wraps the rule engine so callers that pass a raw action list still work
    without creating a full Plan object.
    """
    from core.models import Plan as _Plan

    dummy = _Plan(
        plan_id="eval_tmp",
        mode=state.mode,
        actions=actions,
        score=0.0,
        score_breakdown={},
    )
    _, violations = evaluate_hard_constraints(dummy, state, event)
    return violations
