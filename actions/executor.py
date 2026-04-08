from __future__ import annotations

from core.enums import ActionType
from core.models import Action, Plan, SystemState
from core.state import clone_state, recompute_kpis

from actions.rebalance import apply_rebalance
from actions.reorder import apply_reorder
from actions.reroute import apply_reroute
from actions.switch_supplier import apply_switch_supplier


def apply_action(state: SystemState, action: Action) -> None:
    if action.action_type == ActionType.NO_OP:
        return
    if action.action_type == ActionType.REORDER:
        apply_reorder(state, action)
    elif action.action_type == ActionType.SWITCH_SUPPLIER:
        apply_switch_supplier(state, action)
    elif action.action_type == ActionType.REROUTE:
        apply_reroute(state, action)
    elif action.action_type == ActionType.REBALANCE:
        apply_rebalance(state, action)


def simulate_actions(state: SystemState, actions: list[Action]) -> SystemState:
    simulated = clone_state(state)
    simulated.extra_cost = state.extra_cost
    total_recovery_hours = 0.0
    real_actions = [action for action in actions if action.action_type != ActionType.NO_OP]
    for action in real_actions:
        apply_action(simulated, action)
        total_recovery_hours += max(action.estimated_recovery_hours, 0.0)
    if real_actions:
        avg_recovery = total_recovery_hours / len(real_actions)
        recovery_speed = 1.0 / (1.0 + (avg_recovery / 24.0))
    else:
        recovery_speed = 0.95 if simulated.mode.value == "normal" else 0.60
    simulated.kpis = recompute_kpis(simulated, recovery_speed=recovery_speed)
    return simulated


def apply_plan(state: SystemState, plan: Plan) -> SystemState:
    applied = simulate_actions(state, plan.actions)
    applied.latest_plan = plan
    applied.latest_plan_id = plan.plan_id
    applied.pending_plan = None
    return applied
