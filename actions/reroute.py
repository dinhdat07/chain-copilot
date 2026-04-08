from core.models import Action, SystemState


def apply_reroute(state: SystemState, action: Action) -> None:
    item = state.inventory[action.target_id]
    route_id = action.parameters["route_id"]
    item.preferred_route_id = route_id
    state.extra_cost += max(action.estimated_cost_delta, 0.0)
