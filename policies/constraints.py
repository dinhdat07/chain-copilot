from abc import ABC, abstractmethod
from typing import List, Tuple

from core.enums import ActionType, ConstraintViolationCode
from core.models import Action, Plan, SystemState, Violation


class BaseRule(ABC):
    """Abstract base class for all logistics constraints."""

    @property
    @abstractmethod
    def code(self) -> ConstraintViolationCode:
        """A unique violation code for the rule."""
        pass

    @property
    def priority(self) -> int:
        """Execution priority (lower is higher)."""
        return 100

    @property
    def is_critical(self) -> bool:
        """If True, fails fast on violation."""
        return False

    @abstractmethod
    def evaluate(self, plan: Plan, state: SystemState) -> List[Violation]:
        """Evaluate the plan against state and return violations."""
        pass


# --- Rule Implementations ---

class SupplierExistenceRule(BaseRule):
    code = ConstraintViolationCode.SUPPLIER_NOT_FOUND
    priority = 10
    is_critical = True

    def evaluate(self, plan: Plan, state: SystemState) -> List[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type == ActionType.SWITCH_SUPPLIER:
                # Trích xuất supplier_id từ parameters, nếu không có mới lấy target_id
                supplier_id = action.parameters.get("supplier_id") or action.target_id
                if supplier_id not in state.suppliers:
                    violations.append(Violation(
                        code=self.code,
                        message=f"Supplier {supplier_id} not found in system."
                    ))
        return violations


class SupplierBlockedRule(BaseRule):
    code = ConstraintViolationCode.SUPPLIER_BLOCKED
    priority = 20

    def evaluate(self, plan: Plan, state: SystemState) -> List[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type == ActionType.SWITCH_SUPPLIER:
                supplier_id = action.parameters.get("supplier_id") or action.target_id
                if supplier_id in state.suppliers:
                    supplier = state.suppliers[supplier_id]
                    if supplier.status == "blocked":
                        violations.append(Violation(
                            code=self.code,
                            message=f"Supplier {supplier_id} is currently blocked."
                        ))
        return violations


class RouteExistenceRule(BaseRule):
    code = ConstraintViolationCode.ROUTE_NOT_FOUND
    priority = 10
    is_critical = True

    def evaluate(self, plan: Plan, state: SystemState) -> List[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type == ActionType.REROUTE:
                # Trích xuất route_id từ parameters
                route_id = action.parameters.get("route_id") or action.target_id
                if route_id not in state.routes:
                    violations.append(Violation(
                        code=self.code,
                        message=f"Route {route_id} not found in system."
                    ))
        return violations


class RouteBlockedRule(BaseRule):
    code = ConstraintViolationCode.ROUTE_BLOCKED
    priority = 20

    def evaluate(self, plan: Plan, state: SystemState) -> List[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type == ActionType.REROUTE:
                route_id = action.parameters.get("route_id") or action.target_id
                if route_id in state.routes:
                    route = state.routes[route_id]
                    if route.status == "blocked":
                        violations.append(Violation(
                            code=self.code,
                            message=f"Route {route_id} is currently blocked."
                        ))
        return violations


class WarehouseCapacityRule(BaseRule):
    code = ConstraintViolationCode.CAPACITY_EXCEEDED

    def evaluate(self, plan: Plan, state: SystemState) -> List[Violation]:
        violations = []
        # Tích lũy lượng hàng mới dự kiến theo từng kho
        additions_per_wh = {}

        for action in plan.actions:
            if action.action_type == ActionType.REORDER:
                target_sku = action.target_id
                if target_sku in state.inventory:
                    item = state.inventory[target_sku]
                    wh_id = item.warehouse_id
                    qty = int(action.parameters.get("quantity", 0))
                    additions_per_wh[wh_id] = additions_per_wh.get(wh_id, 0) + qty

        # Sau khi tích lũy, kiểm tra xem tổng lượng hàng mới + tồn kho hiện tại có vượt capacity không
        for wh_id, total_added in additions_per_wh.items():
            if wh_id in state.warehouses:
                wh = state.warehouses[wh_id]
                # Tính lượng hàng hiện tại đang có trong kho đó
                current_in_wh = sum(
                    item.on_hand + item.incoming_qty 
                    for item in state.inventory.values() 
                    if item.warehouse_id == wh_id
                )
                
                if current_in_wh + total_added > wh.capacity:
                    violations.append(Violation(
                        code=self.code,
                        message=(
                            f"Total projected stock in warehouse {wh_id} ({current_in_wh + total_added}) "
                            f"exceeds capacity ({wh.capacity})."
                        )
                    ))
        return violations



class MOQRule(BaseRule):
    code = ConstraintViolationCode.MOQ_NOT_MET

    def evaluate(self, plan: Plan, state: SystemState) -> List[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type == ActionType.REORDER:
                # MOQ có thể truyền trực tiếp hoặc lấy từ inventory metadata (ở đây giả định truyền qua params)
                req_moq = int(action.parameters.get("moq_required", 0))
                qty = int(action.parameters.get("quantity", 0))
                if req_moq and qty < req_moq:
                    violations.append(Violation(
                        code=self.code,
                        message=f"Reorder qty {qty} is below MOQ {req_moq} for {action.target_id}."
                    ))
        return violations


class InventoryShortageRule(BaseRule):
    code = ConstraintViolationCode.INVENTORY_SHORTAGE

    def evaluate(self, plan: Plan, state: SystemState) -> List[Violation]:
        violations = []
        for action in plan.actions:
            # Kiểm tra thiếu hàng áp dụng cho Reorder hoặc Switch Supplier (kiểm tra SKU đích)
            target_sku = action.target_id 
            if target_sku in state.inventory:
                item = state.inventory[target_sku]
                if item.on_hand + item.incoming_qty < item.forecast_qty:
                    violations.append(Violation(
                        code=self.code,
                        message=(
                            f"Inventory shortage for {target_sku}: "
                            f"Available {item.on_hand + item.incoming_qty} < Forecast {item.forecast_qty}"
                        )
                    ))
        return violations


class SupplierCapacityRule(BaseRule):
    code = ConstraintViolationCode.SUPPLIER_CAPACITY_EXCEEDED

    def evaluate(self, plan: Plan, state: SystemState) -> List[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type in [ActionType.REORDER, ActionType.SWITCH_SUPPLIER]:
                target_sku = action.target_id
                if target_sku in state.inventory:
                    item = state.inventory[target_sku]
                    qty = int(action.parameters.get("quantity", 0))
                    # Nếu là reorder bình thường thì lấy forecast hoặc qty
                    if not qty:
                        qty = item.forecast_qty
                    
                    supplier_id = action.parameters.get("supplier_id") or item.preferred_supplier_id
                    if supplier_id in state.suppliers:
                        supplier = state.suppliers[supplier_id]
                        if qty > supplier.capacity:
                            violations.append(Violation(
                                code=self.code,
                                message=f"Order quantity {qty} exceeds supplier {supplier_id} capacity of {supplier.capacity}."
                            ))
        return violations


class SLAViolationRule(BaseRule):
    code = ConstraintViolationCode.SLA_VIOLATED

    def evaluate(self, plan: Plan, state: SystemState) -> List[Violation]:
        violations = []
        for action in plan.actions:
            if action.action_type in [ActionType.REORDER, ActionType.REROUTE]:
                # Lấy route_id từ params hoặc mặc định của SKU
                route_id = action.parameters.get("route_id")
                if not route_id and action.target_id in state.inventory:
                    route_id = state.inventory[action.target_id].preferred_route_id
                
                if route_id and route_id in state.routes:
                    route = state.routes[route_id]
                    max_allowed = int(action.parameters.get("max_eta_days", 999))
                    if route.transit_days > max_allowed:
                        violations.append(Violation(
                            code=self.code,
                            message=f"Route {route_id} ETA {route.transit_days} days exceeds max allowed {max_allowed} days."
                        ))
        return violations


# --- Soft Constraint Rules ---

class BackupSupplierRule(BaseRule):
    code = ConstraintViolationCode.SUPPLIER_BLOCKED  # Dùng code chung hoặc thêm code mới

    def evaluate(self, plan: Plan, state: SystemState) -> List[Violation]:
        warnings = []
        for action in plan.actions:
            if action.action_type == ActionType.SWITCH_SUPPLIER:
                supplier_id = action.parameters.get("supplier_id") or action.target_id
                if supplier_id in state.suppliers:
                    supplier = state.suppliers[supplier_id]
                    if not supplier.is_primary:
                        warnings.append(Violation(
                            code=self.code,
                            message=f"Switching to backup supplier {supplier_id} increases overhead."
                        ))
        return warnings


class CostToleranceRule(BaseRule):
    code = ConstraintViolationCode.CAPACITY_EXCEEDED

    def evaluate(self, plan: Plan, state: SystemState) -> List[Violation]:
        warnings = []
        for action in plan.actions:
            if action.estimated_cost_delta > 5000:
                warnings.append(Violation(
                    code=self.code,
                    message=f"Action '{action.action_id}' has high estimated cost delta (${action.estimated_cost_delta})."
                ))
        return warnings


class LowReliabilityRule(BaseRule):
    code = ConstraintViolationCode.RELIABILITY_LOW

    def evaluate(self, plan: Plan, state: SystemState) -> List[Violation]:
        warnings = []
        for action in plan.actions:
            supplier_id = action.parameters.get("supplier_id")
            if not supplier_id: continue
            
            # Tìm trong danh sách supplier của SKU đó
            for sku_data in state.suppliers.values():
                if sku_data.supplier_id == supplier_id and sku_data.reliability < 0.85:
                    warnings.append(Violation(
                        code=self.code,
                        message=f"Supplier {supplier_id} has low reliability ({sku_data.reliability:.0%})."
                    ))
                    break
        return warnings


class HighRouteRiskRule(BaseRule):
    code = ConstraintViolationCode.RISK_HIGH

    def evaluate(self, plan: Plan, state: SystemState) -> List[Violation]:
        warnings = []
        for action in plan.actions:
            route_id = action.parameters.get("route_id") or action.target_id
            if route_id in state.routes:
                route = state.routes[route_id]
                if route.risk_score > 0.4:
                    warnings.append(Violation(
                        code=self.code,
                        message=f"Route {route_id} has a high risk score ({route.risk_score:.2f})."
                    ))
        return warnings


class WarehouseUtilizationRule(BaseRule):
    code = ConstraintViolationCode.CAPACITY_EXCEEDED

    def evaluate(self, plan: Plan, state: SystemState) -> List[Violation]:
        warnings = []
        additions_per_wh = {}
        for action in plan.actions:
            if action.action_type == ActionType.REORDER:
                item = state.inventory.get(action.target_id)
                if item:
                    wh_id = item.warehouse_id
                    qty = int(action.parameters.get("quantity", 0))
                    additions_per_wh[wh_id] = additions_per_wh.get(wh_id, 0) + qty

        for wh_id, total_added in additions_per_wh.items():
            if wh_id in state.warehouses:
                wh = state.warehouses[wh_id]
                current_in_wh = sum(i.on_hand + i.incoming_qty for i in state.inventory.values() if i.warehouse_id == wh_id)
                utilization = (current_in_wh + total_added) / wh.capacity
                if 0.85 <= utilization <= 1.0:
                    warnings.append(Violation(
                        code=self.code,
                        message=f"Warehouse {wh_id} will be at {utilization:.0%} capacity. Close to limit."
                    ))
        return warnings


# --- Constraint Engine ---


class ConstraintEngine:
    def __init__(self, rules: List[BaseRule]):
        self.rules = sorted(rules, key=lambda r: r.priority)

    def evaluate(self, plan: Plan, state: SystemState) -> Tuple[bool, List[Violation]]:
        all_violations = []
        for rule in self.rules:
            violations = rule.evaluate(plan, state)
            if violations:
                all_violations.extend(violations)
                if rule.is_critical:
                    return False, all_violations
        
        feasible = len(all_violations) == 0
        return feasible, all_violations


# --- Compatibility Layer ---

HARD_RULES = [
    SupplierExistenceRule(),
    SupplierBlockedRule(),
    RouteExistenceRule(),
    RouteBlockedRule(),
    WarehouseCapacityRule(),
    MOQRule(),
    InventoryShortageRule(),
    SupplierCapacityRule(),
    SLAViolationRule(),
]

SOFT_RULES = [
    BackupSupplierRule(),
    CostToleranceRule(),
    LowReliabilityRule(),
    HighRouteRiskRule(),
    WarehouseUtilizationRule(),
]


HARD_ENGINE = ConstraintEngine(HARD_RULES)
SOFT_ENGINE = ConstraintEngine(SOFT_RULES)


def evaluate_hard_constraints(plan: Plan, state: SystemState) -> Tuple[bool, List[Violation]]:
    """Evaluates hard constraints using the modular engine."""
    return HARD_ENGINE.evaluate(plan, state)


def evaluate_soft_constraints(plan: Plan, state: SystemState) -> List[Violation]:
    """Evaluates soft constraints using the modular engine."""
    _, warnings = SOFT_ENGINE.evaluate(plan, state)
    return warnings
