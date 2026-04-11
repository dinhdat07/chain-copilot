from enum import Enum


class Mode(str, Enum):
    NORMAL = "normal"
    CRISIS = "crisis"
    APPROVAL = "approval"


class EventType(str, Enum):
    SUPPLIER_DELAY = "supplier_delay"
    DEMAND_SPIKE = "demand_spike"
    ROUTE_BLOCKAGE = "route_blockage"
    COMPOUND = "compound"
    APPROVAL = "approval"


class ActionType(str, Enum):
    NO_OP = "no_op"
    REORDER = "reorder"
    SWITCH_SUPPLIER = "switch_supplier"
    REROUTE = "reroute"
    REBALANCE = "rebalance"


class PlanStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    APPLIED = "applied"
    REJECTED = "rejected"


class ApprovalStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    AUTO_APPLIED = "auto_applied"
    REJECTED = "rejected"


class ConstraintViolationCode(str, Enum):
    SUPPLIER_NOT_FOUND = "SUPPLIER_NOT_FOUND"
    SUPPLIER_BLOCKED = "SUPPLIER_BLOCKED"
    SUPPLIER_CAPACITY_EXCEEDED = "SUPPLIER_CAPACITY_EXCEEDED"
    ROUTE_NOT_FOUND = "ROUTE_NOT_FOUND"
    ROUTE_BLOCKED = "ROUTE_BLOCKED"
    CAPACITY_EXCEEDED = "CAPACITY_EXCEEDED"
    MOQ_NOT_MET = "MOQ_NOT_MET"
    INVENTORY_SHORTAGE = "INVENTORY_SHORTAGE"
    SLA_VIOLATED = "SLA_VIOLATED"
    RISK_HIGH = "RISK_HIGH"
    RELIABILITY_LOW = "RELIABILITY_LOW"


