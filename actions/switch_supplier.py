from core.models import Action, SystemState


def apply_switch_supplier(state: SystemState, action: Action) -> None:
    item = state.inventory[action.target_id]
    supplier_id = action.parameters["supplier_id"]
    supplier = state.suppliers[supplier_id]
    item.preferred_supplier_id = supplier_id
    item.unit_cost = supplier.unit_cost
    state.extra_cost += max(action.estimated_cost_delta, 0.0)
