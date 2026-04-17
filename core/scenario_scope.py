from __future__ import annotations

from dataclasses import dataclass

from core.enums import EventType
from core.models import Event, SystemState


@dataclass
class ResolvedScenarioScope:
    event_type: str
    route_ids: list[str]
    supplier_ids: list[str]
    affected_skus: list[str]
    route_affected_skus: list[str]
    supplier_affected_skus: list[str]
    demand_affected_skus: list[str]
    warehouse_ids: list[str]
    node_ids: list[str]
    demand_changes: list[dict[str, float | str]]
    component_types: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "event_type": self.event_type,
            "route_ids": list(self.route_ids),
            "supplier_ids": list(self.supplier_ids),
            "affected_skus": list(self.affected_skus),
            "route_affected_skus": list(self.route_affected_skus),
            "supplier_affected_skus": list(self.supplier_affected_skus),
            "demand_affected_skus": list(self.demand_affected_skus),
            "warehouse_ids": list(self.warehouse_ids),
            "node_ids": list(self.node_ids),
            "demand_changes": list(self.demand_changes),
            "component_types": list(self.component_types),
            "direct_scope_summary": direct_scope_summary(self),
        }


def _sorted(values: set[str]) -> list[str]:
    return sorted(str(value) for value in values if str(value).strip())


def _list_from_payload(
    payload: dict[str, object],
    plural_key: str,
    singular_key: str | None = None,
) -> list[str]:
    values = payload.get(plural_key)
    result: list[str] = []
    if isinstance(values, list):
        for value in values:
            text = str(value).strip()
            if text and text not in result:
                result.append(text)
    if singular_key:
        single = str(payload.get(singular_key) or "").strip()
        if single and single not in result:
            result.append(single)
    return result


def payload_route_ids(event: Event | None) -> list[str]:
    if event is None:
        return []
    return _list_from_payload(event.payload, "route_ids", "route_id")


def payload_supplier_ids(event: Event | None) -> list[str]:
    if event is None:
        return []
    return _list_from_payload(event.payload, "supplier_ids", "supplier_id")


def payload_affected_skus(event: Event | None) -> list[str]:
    if event is None:
        return []
    return _list_from_payload(event.payload, "affected_skus", "sku")


def payload_demand_changes(event: Event | None) -> list[dict[str, float | str]]:
    if event is None:
        return []
    raw = event.payload.get("demand_changes")
    if isinstance(raw, list) and raw:
        normalized: list[dict[str, float | str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            sku = str(item.get("sku") or "").strip()
            if not sku:
                continue
            normalized.append(
                {
                    "sku": sku,
                    "multiplier": float(item.get("multiplier", 1.0)),
                }
            )
        if normalized:
            return normalized
    if event.type in {EventType.DEMAND_SPIKE, EventType.COMPOUND}:
        sku = str(event.payload.get("sku") or "").strip()
        if sku:
            return [
                {
                    "sku": sku,
                    "multiplier": float(event.payload.get("multiplier", 1.0)),
                }
            ]
    return []


def direct_scope_summary(scope: ResolvedScenarioScope) -> str:
    parts: list[str] = []
    if scope.route_ids:
        label = "route" if len(scope.route_ids) == 1 else "routes"
        preview = ", ".join(scope.route_ids[:3])
        parts.append(f"{len(scope.route_ids)} {label} ({preview})")
    if scope.supplier_ids:
        label = "supplier" if len(scope.supplier_ids) == 1 else "suppliers"
        preview = ", ".join(scope.supplier_ids[:3])
        parts.append(f"{len(scope.supplier_ids)} {label} ({preview})")
    if scope.affected_skus:
        preview = ", ".join(scope.affected_skus[:4])
        parts.append(f"{len(scope.affected_skus)} SKU(s) ({preview})")
    if scope.warehouse_ids:
        parts.append(f"{len(scope.warehouse_ids)} warehouse(s)")
    if scope.node_ids:
        parts.append(f"{len(scope.node_ids)} node(s)")
    if not parts:
        return "No direct disruption scope was declared."
    return "Directly impacted scope includes " + ", ".join(parts) + "."


def resolve_scenario_scope(
    state: SystemState,
    event: Event | None,
) -> ResolvedScenarioScope:
    if event is None:
        return ResolvedScenarioScope(
            event_type="none",
            route_ids=[],
            supplier_ids=[],
            affected_skus=[],
            route_affected_skus=[],
            supplier_affected_skus=[],
            demand_affected_skus=[],
            warehouse_ids=[],
            node_ids=[],
            demand_changes=[],
            component_types=[],
        )

    route_ids = payload_route_ids(event)
    supplier_ids = payload_supplier_ids(event)
    declared_skus = payload_affected_skus(event)
    demand_changes = payload_demand_changes(event)
    demand_skus = {
        str(item["sku"])
        for item in demand_changes
        if str(item.get("sku") or "").strip()
    }
    route_skus = {
        sku
        for sku, item in state.inventory.items()
        if item.preferred_route_id in route_ids
    }
    supplier_skus = {
        sku
        for sku, item in state.inventory.items()
        if item.preferred_supplier_id in supplier_ids
    }
    affected_skus = set(declared_skus) | demand_skus | route_skus | supplier_skus
    warehouses = {
        state.inventory[sku].warehouse_id
        for sku in affected_skus
        if sku in state.inventory
    }
    nodes: set[str] = set()
    for route_id in route_ids:
        route = state.routes.get(route_id)
        if route is None:
            continue
        nodes.add(route.origin)
        nodes.add(route.destination)

    component_types: list[str] = []
    if route_ids:
        component_types.append("routing")
    if supplier_ids:
        component_types.append("sourcing")
    if demand_changes:
        component_types.append("demand")

    return ResolvedScenarioScope(
        event_type=event.type.value,
        route_ids=route_ids,
        supplier_ids=supplier_ids,
        affected_skus=_sorted(affected_skus),
        route_affected_skus=_sorted(route_skus),
        supplier_affected_skus=_sorted(supplier_skus),
        demand_affected_skus=_sorted(demand_skus),
        warehouse_ids=_sorted(warehouses),
        node_ids=_sorted(nodes),
        demand_changes=demand_changes,
        component_types=component_types,
    )
