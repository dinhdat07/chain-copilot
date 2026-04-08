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
