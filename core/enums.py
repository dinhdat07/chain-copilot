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
    SUPPLIER_NOT_FOUND = "supplier_not_found"
    SUPPLIER_BLOCKED = "supplier_blocked"
    SUPPLIER_CAPACITY_EXCEEDED = "supplier_capacity_exceeded"
    ROUTE_NOT_FOUND = "route_not_found"
    ROUTE_BLOCKED = "route_blocked"
    CAPACITY_EXCEEDED = "warehouse_capacity_exceeded"
    MOQ_NOT_MET = "moq_not_met"
    INVENTORY_SHORTAGE = "inventory_shortage"
    SLA_VIOLATED = "sla_violated"
    RISK_HIGH = "risk_high"
    RELIABILITY_LOW = "reliability_low"


class ExecutionStatus(str, Enum):
    PLANNED                      = "planned"
    APPROVAL_PENDING             = "approval_pending"
    APPROVED                     = "approved"
    DISPATCHED                   = "dispatched"
    APPLIED                      = "applied"        
    IN_PROGRESS                  = "in_progress"   
    COMPLETED                    = "completed"    
    FAILED                       = "failed"
    ROLLED_BACK                  = "rolled_back"


class PlanExecutionStatus(str, Enum):
    PENDING                      = "pending"
    COMPLETED                    = "completed"
    PARTIALLY_APPLIED            = "partially_applied"
    COMPLETED_WITH_ERRORS        = "completed_with_errors"
    REQUIRES_MANUAL_INTERVENTION = "requires_manual_intervention"
