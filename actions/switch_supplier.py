from core.models import Action, SystemState


def apply_switch_supplier(state: SystemState, action: Action) -> None:
    item = state.inventory.get(action.target_id)
    if item is None:
        return

    supplier_id = action.parameters.get("supplier_id")
    if not supplier_id:
        return

    supplier = _resolve_supplier(state, supplier_id, item.sku)
    if supplier is None:
        return

    item.preferred_supplier_id = supplier_id
    item.unit_cost = supplier.unit_cost
    state.extra_cost += max(action.estimated_cost_delta, 0.0)


def _resolve_supplier(state: SystemState, supplier_id: str, sku: str):
    return (
        state.suppliers.get(f"{supplier_id}_{sku}")
        or state.suppliers.get(supplier_id)
    )
