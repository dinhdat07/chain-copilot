from __future__ import annotations

import time
from typing import TypedDict

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
from langgraph.graph import END, START, StateGraph
from orchestrator.router import route_after_planner, route_after_risk


class OrchestrationState(TypedDict):
    state: SystemState
    event: Event | None
    started_at: float


class LangGraphControlTower:
    def __init__(self) -> None:
        self.risk_agent = RiskAgent()
        self.demand_agent = DemandAgent()
        self.inventory_agent = InventoryAgent()
        self.supplier_agent = SupplierAgent()
        self.logistics_agent = LogisticsAgent()
        self.planner_agent = PlannerAgent()
        self.graph = self._compile()

    def _reset_cycle(self, state: SystemState) -> None:
        state.candidate_actions = []
        state.agent_outputs = {}

    def _record_output(self, state: SystemState, output) -> None:
        state.agent_outputs[output.agent] = output
        state.candidate_actions.extend(output.proposals)

    def _finalize(self, state: SystemState, started_at: float) -> SystemState:
        state.timestamp = utc_now()
        state.kpis = recompute_kpis(state, recovery_speed=state.kpis.recovery_speed)
        state.kpis.decision_latency_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        return state

    def risk_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        event = graph_state["event"]
        self._reset_cycle(state)
        if event is not None:
            if event.dedupe_key not in {item.dedupe_key for item in state.active_events}:
                state.active_events.append(event)
        output = self.risk_agent.run(state, event)
        self._record_output(state, output)
        return {"state": state, "event": event, "started_at": graph_state["started_at"]}

    def demand_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        output = self.demand_agent.run(state, graph_state["event"])
        self._record_output(state, output)
        return graph_state

    def inventory_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        output = self.inventory_agent.run(state, graph_state["event"])
        self._record_output(state, output)
        return graph_state

    def supplier_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        output = self.supplier_agent.run(state, graph_state["event"])
        self._record_output(state, output)
        return graph_state

    def logistics_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        output = self.logistics_agent.run(state, graph_state["event"])
        self._record_output(state, output)
        return graph_state

    def planner_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        output = self.planner_agent.run(state, graph_state["event"])
        self._record_output(state, output)
        return graph_state

    def approval_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        state.mode = Mode.APPROVAL
        state = self._finalize(state, graph_state["started_at"])
        return {"state": state, "event": graph_state["event"], "started_at": graph_state["started_at"]}

    def execution_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        event = graph_state["event"]
        if state.latest_plan and not state.latest_plan.approval_required:
            state.latest_plan.status = PlanStatus.APPLIED
            state = apply_plan(state, state.latest_plan)
            if state.decision_logs:
                state.decision_logs[-1].approval_status = ApprovalStatus.AUTO_APPLIED
            state.mode = Mode.CRISIS if event and state.active_events else Mode.NORMAL
        state = self._finalize(state, graph_state["started_at"])
        return {"state": state, "event": event, "started_at": graph_state["started_at"]}

    def _compile(self):
        graph = StateGraph(OrchestrationState)
        graph.add_node("risk", self.risk_node)
        graph.add_node("demand", self.demand_node)
        graph.add_node("inventory", self.inventory_node)
        graph.add_node("supplier", self.supplier_node)
        graph.add_node("logistics", self.logistics_node)
        graph.add_node("planner", self.planner_node)
        graph.add_node("approval", self.approval_node)
        graph.add_node("execution", self.execution_node)

        graph.add_edge(START, "risk")
        graph.add_conditional_edges(
            "risk",
            route_after_risk,
            {
                "normal": "demand",
                "crisis": "demand",
                "approval": "approval",
            },
        )
        graph.add_edge("demand", "inventory")
        graph.add_edge("inventory", "supplier")
        graph.add_edge("supplier", "logistics")
        graph.add_edge("logistics", "planner")
        graph.add_conditional_edges(
            "planner",
            route_after_planner,
            {
                "approval": "approval",
                "execution": "execution",
            },
        )
        graph.add_edge("approval", END)
        graph.add_edge("execution", END)
        return graph.compile()

    def invoke(self, state: SystemState, event: Event | None = None) -> SystemState:
        result = self.graph.invoke(
            {
                "state": state,
                "event": event,
                "started_at": time.perf_counter(),
            }
        )
        return result["state"]


def build_graph() -> LangGraphControlTower:
    return LangGraphControlTower()
