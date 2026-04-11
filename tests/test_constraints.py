from datetime import datetime

from core.enums import ActionType, Mode, ConstraintViolationCode
from core.models import Action, InventoryItem, KPIState, Plan, RouteRecord, SupplierRecord, SystemState, WarehouseRecord
from policies.constraints import evaluate_hard_constraints, evaluate_soft_constraints


def test_evaluate_hard_constraints() -> None:
    state = SystemState(
        run_id="test",
        timestamp=datetime.now(),
        kpis=KPIState(service_level=1.0, total_cost=0, disruption_risk=0, recovery_speed=1.0, stockout_risk=0),
        suppliers={
            "sup_01": SupplierRecord(supplier_id="sup_01", sku="SKU-1", unit_cost=10, lead_time_days=2, reliability=0.9, status="blocked", capacity=50),
            "sup_02": SupplierRecord(supplier_id="sup_02", sku="SKU-1", unit_cost=15, lead_time_days=1, reliability=0.99, status="active", capacity=100),
        },
        routes={
            "rt_01": RouteRecord(route_id="rt_01", origin="A", destination="B", transit_days=2, cost=100.0, risk_score=0.1, status="blocked"),
            "rt_02": RouteRecord(route_id="rt_02", origin="A", destination="B", transit_days=10, cost=200.0, risk_score=0.0, status="active"),
        },
        warehouses={
            "wh_01": WarehouseRecord(warehouse_id="wh_01", name="Main", capacity=100, region="NA"),
        },
        inventory={
            "SKU-1": InventoryItem(sku="SKU-1", on_hand=90, incoming_qty=5, reorder_point=20, safety_stock=10, unit_cost=10, preferred_supplier_id="sup_02", preferred_route_id="rt_02", warehouse_id="wh_01", forecast_qty=120)
        }
    )
    
    # Target invalid supplier
    plan1 = Plan(
        plan_id="p1", mode=Mode.NORMAL, score=0, score_breakdown={},
        actions=[Action(action_id="a1", action_type=ActionType.SWITCH_SUPPLIER, target_id="sup_01")]
    )
    is_feas, vios = evaluate_hard_constraints(plan1, state)
    assert not is_feas
    assert any(v.code == ConstraintViolationCode.SUPPLIER_BLOCKED for v in vios)
    
    # Target invalid route
    plan2 = Plan(
        plan_id="p2", mode=Mode.NORMAL, score=0, score_breakdown={},
        actions=[Action(action_id="a2", action_type=ActionType.REROUTE, target_id="rt_01")]
    )
    is_feas, vios = evaluate_hard_constraints(plan2, state)
    assert not is_feas
    assert any(v.code == ConstraintViolationCode.ROUTE_BLOCKED for v in vios)
    
    # Target capacity breach
    plan3 = Plan(
        plan_id="p3", mode=Mode.NORMAL, score=0, score_breakdown={},
        actions=[Action(action_id="a3", action_type=ActionType.REORDER, target_id="SKU-1", parameters={"quantity": 10})]
    )
    is_feas, vios = evaluate_hard_constraints(plan3, state)
    assert not is_feas
    # This plan should have both INVENTORY_SHORTAGE and CAPACITY_EXCEEDED
    assert any(v.code == ConstraintViolationCode.INVENTORY_SHORTAGE for v in vios)
    assert any(v.code == ConstraintViolationCode.CAPACITY_EXCEEDED for v in vios)
    
    # Target supplier capacity breach
    plan5 = Plan(
        plan_id="p5", mode=Mode.NORMAL, score=0, score_breakdown={},
        actions=[Action(action_id="a5", action_type=ActionType.REORDER, target_id="SKU-1", parameters={"quantity": 150})]
    )
    is_feas, vios = evaluate_hard_constraints(plan5, state)
    assert not is_feas
    assert any(v.code == ConstraintViolationCode.SUPPLIER_CAPACITY_EXCEEDED for v in vios)

    # Target SLA breach
    plan6 = Plan(
        plan_id="p6", mode=Mode.NORMAL, score=0, score_breakdown={},
        actions=[Action(action_id="a6", action_type=ActionType.REORDER, target_id="SKU-1", parameters={"quantity": 2, "route_id": "rt_02", "max_eta_days": 5})]
    )
    is_feas, vios = evaluate_hard_constraints(plan6, state)
    assert not is_feas
    assert any(v.code == ConstraintViolationCode.SLA_VIOLATED for v in vios)


def test_evaluate_soft_constraints() -> None:
    state = SystemState(
        run_id="test",
        timestamp=datetime.now(),
        kpis=KPIState(service_level=1.0, total_cost=0, disruption_risk=0, recovery_speed=1.0, stockout_risk=0),
        suppliers={
            "sup_02": SupplierRecord(supplier_id="sup_02", sku="SKU-1", unit_cost=15, lead_time_days=1, reliability=0.99, is_primary=False),
        }
    )
    
    plan1 = Plan(
        plan_id="p1", mode=Mode.NORMAL, score=0, score_breakdown={},
        actions=[
            Action(action_id="a1", action_type=ActionType.SWITCH_SUPPLIER, target_id="sup_02"),
            Action(action_id="a2", action_type=ActionType.REORDER, target_id="sys", estimated_cost_delta=6000),
        ]
    )
    
    soft_vios = evaluate_soft_constraints(plan1, state)
    assert len(soft_vios) == 2
    assert any(v.code == ConstraintViolationCode.SUPPLIER_BLOCKED for v in soft_vios)
    assert any(v.code == ConstraintViolationCode.CAPACITY_EXCEEDED for v in soft_vios)
