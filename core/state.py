from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core.enums import Mode
from core.models import (
    InventoryItem,
    KPIState,
    MemorySnapshot,
    OrderRecord,
    RouteRecord,
    SupplierRecord,
    SystemState,
    WarehouseRecord,
)


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_csv(name: str, data_dir: Path | None = None) -> pd.DataFrame:
    base = data_dir or DATA_DIR
    return pd.read_csv(base / name)


def _validate_seed_data(
    *,
    inventory_df: pd.DataFrame,
    suppliers_df: pd.DataFrame,
    routes_df: pd.DataFrame,
    warehouses_df: pd.DataFrame,
    orders_df: pd.DataFrame,
) -> None:
    inventory_skus = set(inventory_df["sku"].astype(str))
    supplier_skus = set(suppliers_df["sku"].astype(str))
    route_ids = set(routes_df["route_id"].astype(str))
    warehouse_ids = set(warehouses_df["warehouse_id"].astype(str))
    supplier_pairs = {
        (str(row["supplier_id"]), str(row["sku"]))
        for _, row in suppliers_df.iterrows()
    }

    errors: list[str] = []

    missing_inventory_routes = sorted(
        {
            str(row["preferred_route_id"])
            for _, row in inventory_df.iterrows()
            if str(row["preferred_route_id"]) not in route_ids
        }
    )
    if missing_inventory_routes:
        errors.append(
            f"inventory references unknown routes: {', '.join(missing_inventory_routes)}"
        )

    missing_inventory_warehouses = sorted(
        {
            str(row["warehouse_id"])
            for _, row in inventory_df.iterrows()
            if str(row["warehouse_id"]) not in warehouse_ids
        }
    )
    if missing_inventory_warehouses:
        errors.append(
            "inventory references unknown warehouses: "
            + ", ".join(missing_inventory_warehouses)
        )

    missing_preferred_suppliers = sorted(
        {
            f"{row['preferred_supplier_id']}:{row['sku']}"
            for _, row in inventory_df.iterrows()
            if (str(row["preferred_supplier_id"]), str(row["sku"])) not in supplier_pairs
        }
    )
    if missing_preferred_suppliers:
        errors.append(
            "inventory preferred suppliers missing from suppliers.csv: "
            + ", ".join(missing_preferred_suppliers)
        )

    missing_supplier_inventory = sorted(supplier_skus - inventory_skus)
    if missing_supplier_inventory:
        errors.append(
            "suppliers reference unknown SKUs: " + ", ".join(missing_supplier_inventory)
        )

    missing_order_inventory = sorted(
        {
            str(row["sku"])
            for _, row in orders_df.iterrows()
            if str(row["sku"]) not in inventory_skus
        }
    )
    if missing_order_inventory:
        errors.append(
            "orders reference unknown SKUs: " + ", ".join(missing_order_inventory)
        )

    missing_order_warehouses = sorted(
        {
            str(row["warehouse_id"])
            for _, row in orders_df.iterrows()
            if str(row["warehouse_id"]) not in warehouse_ids
        }
    )
    if missing_order_warehouses:
        errors.append(
            "orders reference unknown warehouses: " + ", ".join(missing_order_warehouses)
        )

    if errors:
        raise ValueError("; ".join(errors))


def _load_historical_cases(data_dir: Path | None = None) -> list:
    """Load historical cases from CSV into HistoricalCase models."""
    from core.models import HistoricalCase
    try:
        df = _read_csv("historical_cases.csv", data_dir)
        cases = []
        for _, row in df.iterrows():
            actions = str(row["actions_taken"]).split("|") if pd.notna(row["actions_taken"]) else []
            cases.append(HistoricalCase(
                case_id=row["case_id"],
                event_type=row["event_type"],
                event_severity=float(row["event_severity"]),
                actions_taken=[a.strip() for a in actions],
                outcome_kpis={
                    "service_level": float(row["outcome_service_level"]),
                    "total_cost": float(row["outcome_total_cost"]),
                    "disruption_risk": float(row["outcome_disruption_risk"]),
                    "recovery_speed": float(row["outcome_recovery_speed"]),
                },
                reflection_notes=str(row["reflection_notes"]),
            ))
        return cases
    except FileNotFoundError:
        return []


def default_memory(data_dir: Path | None = None) -> MemorySnapshot:
    return MemorySnapshot(
        snapshot_id="mem_0",
        timestamp=utc_now(),
        supplier_reliability={},
        route_disruption_priors={},
        scenario_outcomes={},
        last_approved_plan_ids=[],
        historical_cases=_load_historical_cases(data_dir),
    )




def recompute_kpis(state: SystemState, recovery_speed: float | None = None) -> KPIState:
    demand = sum(max(item.forecast_qty, 0) for item in state.inventory.values())
    shortage = sum(
        max(item.forecast_qty - (item.on_hand + item.incoming_qty), 0)
        for item in state.inventory.values()
    )
    holding_cost = sum(
        (item.on_hand + item.incoming_qty) * item.unit_cost for item in state.inventory.values()
    )
    route_cost = sum(
        state.routes[item.preferred_route_id].cost
        for item in state.inventory.values()
        if item.preferred_route_id in state.routes
    )
    total_cost = holding_cost + route_cost + state.extra_cost
    service_level = 1.0 if demand == 0 else max(0.0, min(1.0, 1.0 - (shortage / demand)))
    stockout_risk = 0.0 if demand == 0 else max(0.0, min(1.0, shortage / demand))
    active_risk = [event.severity for event in state.active_events]
    route_risk = [route.risk_score for route in state.routes.values() if route.status != "blocked"]
    disruption_risk = 0.0
    if active_risk or route_risk:
        disruption_risk = sum(active_risk + route_risk[:2]) / max(len(active_risk + route_risk[:2]), 1)
        disruption_risk = min(disruption_risk, 1.0)
    if recovery_speed is None:
        recovery_speed = 0.85 if state.mode == Mode.NORMAL else 0.55
    return KPIState(
        service_level=round(service_level, 4),
        total_cost=round(total_cost, 2),
        disruption_risk=round(disruption_risk, 4),
        recovery_speed=round(max(0.0, min(1.0, recovery_speed)), 4),
        stockout_risk=round(stockout_risk, 4),
        decision_latency_ms=state.kpis.decision_latency_ms if getattr(state, "kpis", None) else 0.0,
    )


def load_initial_state(data_dir: Path | None = None) -> SystemState:
    inventory_df = _read_csv("inventory.csv", data_dir)
    suppliers_df = _read_csv("suppliers.csv", data_dir)
    routes_df = _read_csv("routes.csv", data_dir)
    warehouses_df = _read_csv("warehouses.csv", data_dir)
    orders_df = _read_csv("orders.csv", data_dir)
    _validate_seed_data(
        inventory_df=inventory_df,
        suppliers_df=suppliers_df,
        routes_df=routes_df,
        warehouses_df=warehouses_df,
        orders_df=orders_df,
    )

    inventory = {
        row["sku"]: InventoryItem(**row.to_dict())
        for _, row in inventory_df.iterrows()
    }
    suppliers = {
        f"{row['supplier_id']}_{row['sku']}": SupplierRecord(**row.to_dict())
        for _, row in suppliers_df.iterrows()
    }
    routes = {
        row["route_id"]: RouteRecord(**row.to_dict())
        for _, row in routes_df.iterrows()
    }
    warehouses = {
        row["warehouse_id"]: WarehouseRecord(**row.to_dict())
        for _, row in warehouses_df.iterrows()
    }
    orders = [OrderRecord(**row.to_dict()) for _, row in orders_df.iterrows()]

    state = SystemState(
        run_id="run_0",
        timestamp=utc_now(),
        inventory=inventory,
        suppliers=suppliers,
        routes=routes,
        warehouses=warehouses,
        orders=orders,
        kpis=KPIState(
            service_level=1.0,
            total_cost=0.0,
            disruption_risk=0.0,
            recovery_speed=0.85,
            stockout_risk=0.0,
            decision_latency_ms=0.0,
        ),
        memory=default_memory(),
    )
    state.kpis = recompute_kpis(state)
    return state


def clone_state(state: SystemState) -> SystemState:
    return state.model_copy(deep=True)


def state_summary(state: SystemState) -> dict[str, object]:
    return {
        "mode": state.mode.value,
        "active_events": [event.type.value for event in state.active_events],
        "inventory_items": len(state.inventory),
        "suppliers": len(state.suppliers),
        "routes": len(state.routes),
        "kpis": state.kpis.model_dump(),
        "latest_plan_id": state.latest_plan_id,
        "pending_plan_id": state.pending_plan.plan_id if state.pending_plan else None,
    }
