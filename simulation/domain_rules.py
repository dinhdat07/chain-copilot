from __future__ import annotations

from dataclasses import dataclass, field

from core.scenario_scope import (
    payload_demand_changes,
    payload_route_ids,
    payload_supplier_ids,
    resolve_scenario_scope,
)
from core.enums import ActionType, EventType
from core.models import Action, Event, InventoryItem, SystemState
from core.state import recompute_kpis


SIMULATION_HORIZON_DAYS = 3


@dataclass
class SimulationContext:
    working_state: SystemState
    baseline_forecast_by_sku: dict[str, int]
    backlog_by_sku: dict[str, int] = field(default_factory=dict)
    inbound_schedule: dict[int, dict[str, int]] = field(default_factory=dict)
    original_incoming_by_sku: dict[str, int] = field(default_factory=dict)
    event_severity: float = 0.0
    mitigation_count: int = 0


def _supplier_for_item(state: SystemState, item: InventoryItem):
    return state.suppliers.get(
        f"{item.preferred_supplier_id}_{item.sku}"
    ) or state.suppliers.get(item.preferred_supplier_id)


def _route_for_item(state: SystemState, item: InventoryItem):
    return state.routes.get(item.preferred_route_id)


def _event_type(event: Event | None) -> EventType | None:
    return event.type if event is not None else None


def _affected_skus(event: Event | None) -> set[str]:
    if event is None:
        return set()
    return {
        str(item["sku"])
        for item in payload_demand_changes(event)
        if str(item.get("sku") or "").strip()
    } | {
        str(sku)
        for sku in event.payload.get("affected_skus", [])
        if str(sku).strip()
    } | ({str(event.payload.get("sku"))} if event.payload.get("sku") else set())


def _demand_change_map(event: Event | None) -> dict[str, float]:
    if event is None or event.type not in {EventType.DEMAND_SPIKE, EventType.COMPOUND}:
        return {}
    return {
        str(item["sku"]): float(item.get("multiplier", 1.0))
        for item in payload_demand_changes(event)
    }


def _event_penalty_days(
    *,
    event: Event | None,
    supplier_id: str | None = None,
    route_id: str | None = None,
) -> int:
    if event is None:
        return 0
    severity_penalty = (
        2 if event.severity >= 0.85 else 1 if event.severity >= 0.55 else 0
    )
    if event.type == EventType.SUPPLIER_DELAY:
        affected_suppliers = set(payload_supplier_ids(event))
        if supplier_id and supplier_id in affected_suppliers:
            return max(1, severity_penalty)
    if event.type == EventType.ROUTE_BLOCKAGE:
        affected_routes = set(payload_route_ids(event))
        if route_id and route_id in affected_routes:
            return max(1, severity_penalty)
    if event.type == EventType.COMPOUND:
        supplier_match = supplier_id and supplier_id in set(payload_supplier_ids(event))
        route_match = route_id and route_id in set(payload_route_ids(event))
        if supplier_match or route_match:
            return max(1, severity_penalty)
    return 0


def _route_delay_days(
    state: SystemState, item: InventoryItem, event: Event | None
) -> int:
    route = _route_for_item(state, item)
    if route is None:
        return 0
    blocked_penalty = 2 if route.status == "blocked" else 0
    risk_penalty = 1 if route.risk_score >= 0.65 else 0
    return (
        blocked_penalty
        + risk_penalty
        + _event_penalty_days(
            event=event,
            route_id=route.route_id,
        )
    )


def _arrival_step_for_item(
    state: SystemState,
    item: InventoryItem,
    *,
    event: Event | None,
    expedited: bool = False,
) -> int:
    supplier = _supplier_for_item(state, item)
    route = _route_for_item(state, item)
    lead_time = max(int(supplier.lead_time_days), 1) if supplier is not None else 1
    transit = max(int(route.transit_days), 0) if route is not None else 0
    route_penalty = _route_delay_days(state, item, event)
    supplier_penalty = _event_penalty_days(
        event=event,
        supplier_id=supplier.supplier_id if supplier is not None else None,
    )
    raw_days = lead_time + transit + route_penalty + supplier_penalty
    if expedited:
        raw_days = max(raw_days - 1, 1)
    return max(1, min(SIMULATION_HORIZON_DAYS, raw_days))


def initialize_context(state: SystemState, event: Event | None) -> SimulationContext:
    baseline_forecast = {
        sku: max(int(item.forecast_qty), 0) for sku, item in state.inventory.items()
    }
    context = SimulationContext(
        working_state=state,
        baseline_forecast_by_sku=baseline_forecast,
        original_incoming_by_sku={
            sku: max(int(item.incoming_qty), 0) for sku, item in state.inventory.items()
        },
        event_severity=event.severity if event is not None else 0.0,
    )
    for sku, item in state.inventory.items():
        inbound_qty = max(int(item.incoming_qty), 0)
        if inbound_qty <= 0:
            item.incoming_qty = 0
            continue
        arrival_step = _arrival_step_for_item(state, item, event=event)
        context.inbound_schedule.setdefault(arrival_step, {})
        context.inbound_schedule[arrival_step][sku] = (
            context.inbound_schedule[arrival_step].get(sku, 0) + inbound_qty
        )
        item.incoming_qty = 0
    _refresh_future_incoming(context)
    state.kpis = recompute_kpis(state)
    return context


def apply_candidate_actions(
    context: SimulationContext,
    actions: list[Action],
    *,
    event: Event | None,
) -> None:
    state = context.working_state
    for action in actions:
        if action.action_type == ActionType.NO_OP:
            continue
        if action.action_type == ActionType.SWITCH_SUPPLIER:
            item = state.inventory.get(action.target_id)
            if item is None:
                continue
            supplier_id = str(action.parameters.get("supplier_id") or "")
            supplier = state.suppliers.get(
                f"{supplier_id}_{item.sku}"
            ) or state.suppliers.get(supplier_id)
            if supplier is None:
                continue
            item.preferred_supplier_id = supplier_id
            item.unit_cost = supplier.unit_cost
        elif action.action_type == ActionType.REROUTE:
            item = state.inventory.get(action.target_id)
            route_id = str(action.parameters.get("route_id") or "")
            if item is None or not route_id:
                continue
            item.preferred_route_id = route_id
        elif action.action_type == ActionType.REORDER:
            item = state.inventory.get(action.target_id)
            if item is None:
                continue
            quantity = max(int(action.parameters.get("quantity", 0)), 0)
            if quantity <= 0:
                continue
            supplier = _supplier_for_item(state, item)
            capacity = (
                max(int(supplier.capacity), 0) if supplier is not None else quantity
            )
            scheduled_qty = min(quantity, capacity) if capacity > 0 else quantity
            arrival_step = _arrival_step_for_item(state, item, event=event)
            context.inbound_schedule.setdefault(arrival_step, {})
            context.inbound_schedule[arrival_step][item.sku] = (
                context.inbound_schedule[arrival_step].get(item.sku, 0) + scheduled_qty
            )
        elif action.action_type == ActionType.REBALANCE:
            item = state.inventory.get(action.target_id)
            if item is None:
                continue
            quantity = max(int(action.parameters.get("quantity", 0)) // 2, 0)
            if quantity <= 0:
                continue
            arrival_step = 1
            context.inbound_schedule.setdefault(arrival_step, {})
            context.inbound_schedule[arrival_step][item.sku] = (
                context.inbound_schedule[arrival_step].get(item.sku, 0) + quantity
            )
        state.extra_cost += max(action.estimated_cost_delta, 0.0)
        context.mitigation_count += 1
    _refresh_future_incoming(context)
    state.kpis = recompute_kpis(state)


def advance_demand(
    context: SimulationContext, *, step_index: int, event: Event | None
) -> None:
    state = context.working_state
    event_type = _event_type(event)
    demand_changes = _demand_change_map(event)
    if event_type not in {EventType.DEMAND_SPIKE, EventType.COMPOUND} or not demand_changes:
        for sku, item in state.inventory.items():
            item.forecast_qty = context.baseline_forecast_by_sku.get(
                sku, item.forecast_qty
            )
        return

    decay_ratio = 0.55 ** max(step_index - 1, 0)
    for sku, item in state.inventory.items():
        base = context.baseline_forecast_by_sku.get(sku, item.forecast_qty)
        if sku in demand_changes:
            spike_multiplier = demand_changes[sku]
            active_multiplier = 1.0 + max(spike_multiplier - 1.0, 0.0) * decay_ratio
            item.forecast_qty = max(int(round(base * active_multiplier)), 0)
        else:
            item.forecast_qty = base


def advance_supplier(
    context: SimulationContext, *, step_index: int, event: Event | None
) -> list[str]:
    state = context.working_state
    observations: list[str] = []
    if event is None:
        return observations
    if event.type not in {EventType.SUPPLIER_DELAY, EventType.COMPOUND}:
        return observations
    scope = resolve_scenario_scope(state, event)
    affected_skus = set(scope.supplier_affected_skus or scope.affected_skus)
    for item in state.inventory.values():
        if affected_skus and item.sku not in affected_skus:
            continue
        supplier = _supplier_for_item(state, item)
        if supplier is None:
            continue
        if supplier.reliability < 0.85 and step_index == 1:
            observations.append(
                f"{item.sku} still depends on supplier reliability of {supplier.reliability:.0%}"
            )
    return observations


def advance_logistics(
    context: SimulationContext, *, step_index: int, event: Event | None
) -> list[str]:
    state = context.working_state
    observations: list[str] = []
    if event is None:
        return observations
    if event.type not in {EventType.ROUTE_BLOCKAGE, EventType.COMPOUND}:
        return observations
    scope = resolve_scenario_scope(state, event)
    affected_skus = set(scope.route_affected_skus or scope.affected_skus)
    blocked_routes = set(scope.route_ids)
    for item in state.inventory.values():
        if affected_skus and item.sku not in affected_skus:
            continue
        route = _route_for_item(state, item)
        if route is None:
            continue
        if route.route_id in blocked_routes or route.status == "blocked":
            observations.append(
                f"{item.sku} remains exposed to blocked route {route.route_id}"
            )
        elif route.risk_score >= 0.6 and step_index == 1:
            observations.append(
                f"{item.sku} still uses a high-risk lane ({route.route_id}, risk {route.risk_score:.0%})"
            )
    return observations


def advance_inventory(context: SimulationContext, *, step_index: int) -> dict[str, int]:
    state = context.working_state
    inbound_due = context.inbound_schedule.get(step_index, {})
    total_inbound = 0
    total_backlog = 0
    at_risk = 0
    out_of_stock = 0

    for sku, item in state.inventory.items():
        arriving = max(int(inbound_due.get(sku, 0)), 0)
        if arriving:
            item.on_hand += arriving
            total_inbound += arriving

        backlog = max(int(context.backlog_by_sku.get(sku, 0)), 0)
        demand = max(int(item.forecast_qty), 0)
        required = backlog + demand
        served = min(max(int(item.on_hand), 0), required)
        item.on_hand = max(int(item.on_hand) - served, 0)
        remaining_backlog = max(required - served, 0)
        context.backlog_by_sku[sku] = remaining_backlog
        total_backlog += remaining_backlog

        if item.on_hand <= 0 and remaining_backlog > 0:
            out_of_stock += 1
        elif item.on_hand + item.incoming_qty <= max(item.safety_stock, 0):
            at_risk += 1
        elif item.on_hand + item.incoming_qty <= max(item.reorder_point, 0):
            at_risk += 1

    _refresh_future_incoming(context)
    state.kpis = recompute_kpis(state)
    return {
        "inbound_units_due": total_inbound,
        "backlog_units": total_backlog,
        "inventory_at_risk": at_risk,
        "inventory_out_of_stock": out_of_stock,
    }


def advance_risk(
    context: SimulationContext,
    *,
    event: Event | None,
    step_metrics: dict[str, int],
) -> float:
    state = context.working_state
    if event is None:
        context.event_severity = 0.0
        return context.event_severity

    unresolved_pressure = 0.0
    if state.inventory:
        unresolved_pressure = step_metrics["inventory_out_of_stock"] / max(
            len(state.inventory), 1
        )
    improvement = min(context.mitigation_count * 0.03, 0.15)
    decay = 0.08 + improvement
    escalation = 0.05 if unresolved_pressure >= 0.08 else 0.0
    context.event_severity = max(
        0.0,
        min(1.0, context.event_severity - decay + escalation),
    )
    if state.active_events:
        state.active_events[-1].severity = round(context.event_severity, 4)
    state.kpis = recompute_kpis(
        state,
        recovery_speed=_projected_recovery_speed(context, step_metrics),
    )
    return context.event_severity


def _projected_recovery_speed(
    context: SimulationContext,
    step_metrics: dict[str, int],
) -> float:
    state = context.working_state
    at_risk_ratio = step_metrics["inventory_at_risk"] / max(len(state.inventory), 1)
    backlog_ratio = step_metrics["backlog_units"] / max(
        sum(max(item.forecast_qty, 0) for item in state.inventory.values()),
        1,
    )
    base = 0.9 if state.mode.value == "normal" else 0.65
    improvement = min(context.mitigation_count * 0.015, 0.12)
    penalty = min((at_risk_ratio * 0.25) + (backlog_ratio * 0.35), 0.35)
    return max(0.05, min(0.99, base + improvement - penalty))


def dominant_constraint(
    context: SimulationContext, step_metrics: dict[str, int]
) -> str:
    state = context.working_state
    active_event = state.active_events[-1] if state.active_events else None
    scope = resolve_scenario_scope(state, active_event)
    blocked_routes = set(scope.route_ids)
    delayed_suppliers = set(scope.supplier_ids)
    if step_metrics["inventory_out_of_stock"] > 0:
        return "inventory shortfall"
    if step_metrics["backlog_units"] > 0:
        return "order backlog"
    if any(
        (
            _route_for_item(state, item) is not None
            and (
                _route_for_item(state, item).status == "blocked"
                or _route_for_item(state, item).route_id in blocked_routes
            )
        )
        for item in state.inventory.values()
    ):
        return "route disruption"
    if any(
        (
            _supplier_for_item(state, item) is not None
            and (
                _supplier_for_item(state, item).reliability < 0.85
                or _supplier_for_item(state, item).supplier_id in delayed_suppliers
            )
        )
        for item in state.inventory.values()
    ):
        return "supplier reliability"
    return "demand pressure"


def step_summary(
    context: SimulationContext,
    *,
    step_index: int,
    step_metrics: dict[str, int],
    change_notes: list[str],
) -> str:
    parts = [
        f"T+{step_index} projects service at {context.working_state.kpis.service_level:.0%}",
        f"risk at {context.working_state.kpis.disruption_risk:.0%}",
    ]
    if step_metrics["inventory_out_of_stock"] > 0:
        parts.append(
            f"{step_metrics['inventory_out_of_stock']} SKU(s) remain out of stock"
        )
    elif step_metrics["inventory_at_risk"] > 0:
        parts.append(f"{step_metrics['inventory_at_risk']} SKU(s) remain at risk")
    if step_metrics["inbound_units_due"] > 0:
        parts.append(f"{step_metrics['inbound_units_due']} inbound units arrive")
    if step_metrics["backlog_units"] > 0:
        parts.append(f"backlog holds at {step_metrics['backlog_units']} units")
    if change_notes:
        parts.append(change_notes[0])
    return ", ".join(parts)


def _refresh_future_incoming(context: SimulationContext) -> None:
    state = context.working_state
    for sku, item in state.inventory.items():
        remaining = 0
        for scheduled in context.inbound_schedule.values():
            remaining += max(int(scheduled.get(sku, 0)), 0)
        item.incoming_qty = remaining
