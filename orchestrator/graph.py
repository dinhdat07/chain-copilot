from __future__ import annotations

import time

from actions.executor import apply_plan
from agents.demand import DemandAgent
from agents.inventory import InventoryAgent
from agents.logistics import LogisticsAgent
from agents.planner import PlannerAgent
from agents.risk import RiskAgent
from agents.supplier import SupplierAgent
from core.enums import ApprovalStatus, Mode, PlanStatus
from core.models import Event, SystemState
from core.state import recompute_kpis, utc_now


class ControlTowerGraph:
    def __init__(self) -> None:
        self.risk_agent = RiskAgent()
        self.demand_agent = DemandAgent()
        self.inventory_agent = InventoryAgent()
        self.supplier_agent = SupplierAgent()
        self.logistics_agent = LogisticsAgent()
        self.planner_agent = PlannerAgent()

    def _reset_cycle(self, state: SystemState) -> None:
        state.candidate_actions = []
        state.agent_outputs = {}

    def _record_output(self, state: SystemState, output) -> None:
        state.agent_outputs[output.agent] = output
        state.candidate_actions.extend(output.proposals)

    def invoke(self, state: SystemState, event: Event | None = None) -> SystemState:
        self._reset_cycle(state)
        started = time.perf_counter()
        if event is not None:
            if event.dedupe_key not in {item.dedupe_key for item in state.active_events}:
                state.active_events.append(event)
        risk_output = self.risk_agent.run(state, event)
        self._record_output(state, risk_output)

        for agent in (
            self.demand_agent,
            self.inventory_agent,
            self.supplier_agent,
            self.logistics_agent,
            self.planner_agent,
        ):
            output = agent.run(state, event)
            self._record_output(state, output)

        if state.latest_plan and not state.latest_plan.approval_required:
            state.latest_plan.status = PlanStatus.APPLIED
            state = apply_plan(state, state.latest_plan)
            if state.decision_logs:
                state.decision_logs[-1].approval_status = ApprovalStatus.AUTO_APPLIED
            state.mode = Mode.CRISIS if event and state.active_events else Mode.NORMAL
        else:
            state.mode = Mode.APPROVAL
        state.timestamp = utc_now()
        state.kpis = recompute_kpis(state, recovery_speed=state.kpis.recovery_speed)
        state.kpis.decision_latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return state


def build_graph() -> ControlTowerGraph:
    return ControlTowerGraph()
