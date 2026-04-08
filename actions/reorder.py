from core.models import Action, SystemState


def apply_reorder(state: SystemState, action: Action) -> None:
    item = state.inventory[action.target_id]
    quantity = int(action.parameters.get("quantity", 0))
    item.incoming_qty += max(quantity, 0)
    state.extra_cost += max(action.estimated_cost_delta, 0.0)
