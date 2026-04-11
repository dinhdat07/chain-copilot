from __future__ import annotations

from core.enums import ActionType, EventType, Mode
from core.models import Action, ConstraintViolation, Event, SystemState


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


def evaluate_plan_constraints(
    *,
    state: SystemState,
    event: Event | None,
    actions: list[Action],
) -> list[ConstraintViolation]:
    violations: list[ConstraintViolation] = []
    blocked_routes = _blocked_routes(state, event)
    delayed_suppliers = _delayed_suppliers(state, event)

    for action in actions:
        if action.action_type == ActionType.NO_OP:
            continue
        if action.action_type == ActionType.SWITCH_SUPPLIER:
            supplier_id = str(action.parameters.get("supplier_id", ""))
            supplier = state.suppliers.get(supplier_id)
            target_item = state.inventory.get(action.target_id)
            if supplier is None:
                violations.append(
                    ConstraintViolation(
                        code="supplier_missing",
                        message=f"supplier {supplier_id} does not exist",
                        action_id=action.action_id,
                        severity="hard",
                    )
                )
            elif supplier.status != "active":
                violations.append(
                    ConstraintViolation(
                        code="supplier_inactive",
                        message=f"supplier {supplier_id} is not active",
                        action_id=action.action_id,
                        severity="hard",
                    )
                )
            elif supplier.sku != action.target_id:
                violations.append(
                    ConstraintViolation(
                        code="supplier_sku_mismatch",
                        message=f"supplier {supplier_id} does not supply {action.target_id}",
                        action_id=action.action_id,
                        severity="hard",
                    )
                )
            elif supplier_id in delayed_suppliers:
                violations.append(
                    ConstraintViolation(
                        code="supplier_delayed",
                        message=f"supplier {supplier_id} is currently delayed by an active disruption",
                        action_id=action.action_id,
                        severity="hard",
                    )
                )
            elif target_item is None:
                violations.append(
                    ConstraintViolation(
                        code="inventory_target_missing",
                        message=f"inventory target {action.target_id} does not exist",
                        action_id=action.action_id,
                        severity="hard",
                    )
                )
        elif action.action_type == ActionType.REROUTE:
            route_id = str(action.parameters.get("route_id", ""))
            route = state.routes.get(route_id)
            if route is None:
                violations.append(
                    ConstraintViolation(
                        code="route_missing",
                        message=f"route {route_id} does not exist",
                        action_id=action.action_id,
                        severity="hard",
                    )
                )
            elif route.status == "blocked" or route_id in blocked_routes:
                violations.append(
                    ConstraintViolation(
                        code="route_blocked",
                        message=f"route {route_id} is blocked by an active disruption",
                        action_id=action.action_id,
                        severity="hard",
                    )
                )
        elif action.action_type == ActionType.REORDER:
            item = state.inventory.get(action.target_id)
            quantity = int(action.parameters.get("quantity", 0) or 0)
            if item is None:
                violations.append(
                    ConstraintViolation(
                        code="inventory_target_missing",
                        message=f"inventory target {action.target_id} does not exist",
                        action_id=action.action_id,
                        severity="hard",
                    )
                )
                continue
            if quantity <= 0:
                violations.append(
                    ConstraintViolation(
                        code="reorder_quantity_invalid",
                        message="reorder quantity must be greater than zero",
                        action_id=action.action_id,
                        severity="hard",
                    )
                )
            warehouse = state.warehouses.get(item.warehouse_id)
            projected_total = item.on_hand + item.incoming_qty + quantity
            if warehouse is not None and projected_total > warehouse.capacity:
                violations.append(
                    ConstraintViolation(
                        code="warehouse_capacity_exceeded",
                        message=(
                            f"warehouse {warehouse.warehouse_id} capacity {warehouse.capacity} "
                            f"would be exceeded by projected total {projected_total}"
                        ),
                        action_id=action.action_id,
                        severity="hard",
                    )
                )
        elif action.action_type == ActionType.REBALANCE:
            item = state.inventory.get(action.target_id)
            quantity = int(action.parameters.get("quantity", 0) or 0)
            available = 0 if item is None else item.on_hand + item.incoming_qty
            if item is None:
                violations.append(
                    ConstraintViolation(
                        code="inventory_target_missing",
                        message=f"inventory target {action.target_id} does not exist",
                        action_id=action.action_id,
                        severity="hard",
                    )
                )
            elif quantity <= 0:
                violations.append(
                    ConstraintViolation(
                        code="rebalance_quantity_invalid",
                        message="rebalance quantity must be greater than zero",
                        action_id=action.action_id,
                        severity="hard",
                    )
                )
            elif quantity > available:
                violations.append(
                    ConstraintViolation(
                        code="inventory_insufficient",
                        message=(
                            f"rebalance quantity {quantity} exceeds available inventory {available} "
                            f"for {action.target_id}"
                        ),
                        action_id=action.action_id,
                        severity="hard",
                    )
                )
    return violations
