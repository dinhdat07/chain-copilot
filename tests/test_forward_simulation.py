from __future__ import annotations

from core.enums import ActionType, EventType
from core.models import Action
from core.state import load_initial_state
from simulation.evaluator import evaluate_candidate_plan
from simulation.scenarios import build_event


def _stressed_sku_state():
    state = load_initial_state()
    sku = next(iter(state.inventory))
    item = state.inventory[sku]
    item.on_hand = 5
    item.incoming_qty = 0
    item.forecast_qty = max(item.forecast_qty, 80)
    item.reorder_point = max(item.reorder_point, 90)
    item.safety_stock = max(item.safety_stock, 30)
    supplier = state.suppliers.get(f"{item.preferred_supplier_id}_{sku}")
    if supplier is not None:
        supplier.lead_time_days = 1
    route = state.routes.get(item.preferred_route_id)
    if route is not None:
        route.transit_days = 0
        route.risk_score = min(route.risk_score, 0.2)
    return state, sku


def test_forward_projection_returns_three_timeline_steps() -> None:
    state, sku = _stressed_sku_state()
    action = Action(
        action_id=f"act_reorder_{sku}",
        action_type=ActionType.REORDER,
        target_id=sku,
        parameters={"quantity": 160},
        estimated_cost_delta=1200.0,
        estimated_service_delta=0.12,
        estimated_risk_delta=-0.08,
        estimated_recovery_hours=24.0,
        reason="expedite replenishment",
        priority=0.9,
    )

    projection = evaluate_candidate_plan(state=state, event=None, actions=[action])

    assert projection.simulation_horizon_days == 3
    assert [step.label for step in projection.projection_steps] == ["T+1", "T+2", "T+3"]
    assert projection.projected_state_summary is not None
    assert projection.projection_summary


def test_reorder_improves_projected_outcome_and_mitigation_lowers_severity() -> None:
    state, sku = _stressed_sku_state()
    event = build_event(
        event_id="evt_test_demand_spike",
        event_type=EventType.DEMAND_SPIKE,
        severity=0.72,
        payload={"sku": sku, "multiplier": 1.8},
        entity_ids=[sku],
    )
    no_op_projection = evaluate_candidate_plan(state=state, event=event, actions=[])
    reorder_projection = evaluate_candidate_plan(
        state=state,
        event=event,
        actions=[
            Action(
                action_id=f"act_reorder_{sku}",
                action_type=ActionType.REORDER,
                target_id=sku,
                parameters={"quantity": 180},
                estimated_cost_delta=1400.0,
                estimated_service_delta=0.15,
                estimated_risk_delta=-0.1,
                estimated_recovery_hours=24.0,
                reason="cover demand spike",
                priority=0.95,
            )
        ],
    )

    assert reorder_projection.projected_kpis.service_level >= no_op_projection.projected_kpis.service_level
    assert reorder_projection.projected_state_summary.backlog_units <= no_op_projection.projected_state_summary.backlog_units
    assert reorder_projection.projected_state_summary.event_severity_end <= no_op_projection.projected_state_summary.event_severity_end
