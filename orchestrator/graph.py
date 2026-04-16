from __future__ import annotations

import time
from typing import Callable, TypedDict
from uuid import uuid4

from actions.executor import apply_plan
from agents.critic import CriticAgent
from agents.demand import DemandAgent
from agents.inventory import InventoryAgent
from agents.logistics import LogisticsAgent
from agents.planner import PlannerAgent
from agents.risk import RiskAgent
from agents.supplier import SupplierAgent
from core.enums import ApprovalStatus, Mode, PlanStatus
from core.models import (
    AgentProposal,
    Event,
    OrchestrationTrace,
    SystemState,
    TraceRouteDecision,
    TraceStep,
)
from core.runtime_tracking import new_run_id
from core.scenario_scope import resolve_scenario_scope
from core.state import recompute_kpis, utc_now
from langgraph.graph import END, START, StateGraph
from orchestrator.router import (
    route_after_demand,
    route_after_inventory,
    route_after_logistics,
    route_after_critic,
    route_after_planner,
    route_after_risk,
    route_after_supplier,
)


class OrchestrationState(TypedDict, total=False):
    state: SystemState
    event: Event | None
    started_at: float
    run_id: str | None
    trace_updater: "Callable[[OrchestrationTrace], None]"


class LangGraphControlTower:
    def __init__(self) -> None:
        self.risk_agent = RiskAgent()
        self.demand_agent = DemandAgent()
        self.inventory_agent = InventoryAgent()
        self.supplier_agent = SupplierAgent()
        self.logistics_agent = LogisticsAgent()
        self.planner_agent = PlannerAgent()
        self.critic_agent = CriticAgent()
        self.graph = self._compile()

    def _emit(
        self,
        graph_state: "OrchestrationState",
        *,
        type: str,
        agent: str,
        step: str,
        message: str,
        data: dict | None = None,
    ) -> None:
        """
        Emits a ThinkingEvent to the EventBus for the current run_id.
        No-op if graph_state has no run_id (backward compat).
        Does not raise exceptions — emit errors should not block the graph.
        """
        run_id = graph_state.get("run_id")
        if not run_id:
            return
        try:
            from streaming.event_bus import event_bus
            from streaming.schemas import ThinkingEvent

            event_bus.publish(
                run_id,
                ThinkingEvent(
                    type=type,  # type: ignore[arg-type]
                    agent=agent,
                    step=step,
                    message=message,
                    data=data or {},
                    timestamp=utc_now(),
                ),
            )
        except Exception:
            pass  # emit failure must NEVER break the graph

    def _reset_cycle(self, state: SystemState) -> None:
        state.candidate_actions = []
        state.agent_outputs = {}
        state.latest_trace = None

    def _begin_trace(self, state: SystemState, event: Event | None) -> None:
        state.latest_trace = OrchestrationTrace(
            trace_id=f"trace_{uuid4().hex[:8]}",
            run_id=state.run_id,
            started_at=utc_now(),
            mode_before=state.mode.value,
            current_branch=state.mode.value,
            event=event.model_copy(deep=True) if event else None,
        )

    def _base_input_snapshot(
        self, state: SystemState, event: Event | None
    ) -> dict[str, object]:
        return {
            "mode": state.mode.value,
            "active_event_count": len(state.active_events),
            "candidate_action_count": len(state.candidate_actions),
            "pending_plan_id": state.pending_plan.plan_id
            if state.pending_plan
            else None,
            "event_type": event.type.value if event else None,
            "event_severity": event.severity if event else None,
        }

    def _start_step(
        self,
        state: SystemState,
        node_key: str,
        node_type: str,
        event: Event | None,
    ) -> None:
        if state.latest_trace is None:
            return
        state.latest_trace.steps.append(
            TraceStep(
                step_id=f"step_{uuid4().hex[:8]}",
                sequence=len(state.latest_trace.steps) + 1,
                node_key=node_key,
                node_type=node_type,
                started_at=utc_now(),
                mode_snapshot=state.mode.value,
                input_snapshot=self._base_input_snapshot(state, event),
            )
        )

    def _complete_step(
        self,
        state: SystemState,
        *,
        node_key: str,
        summary: str,
        reasoning_source: str,
        observations: list[str] | None = None,
        risks: list[str] | None = None,
        downstream_impacts: list[str] | None = None,
        recommended_action_ids: list[str] | None = None,
        tradeoffs: list[str] | None = None,
        llm_used: bool = False,
        llm_error: str | None = None,
        output_snapshot: dict[str, object] | None = None,
    ) -> None:
        if state.latest_trace is None:
            return
        for step in reversed(state.latest_trace.steps):
            if step.node_key != node_key or step.completed_at is not None:
                continue
            step.completed_at = utc_now()
            step.status = "completed"
            step.duration_ms = round(
                max(
                    (step.completed_at - step.started_at).total_seconds() * 1000.0, 0.0
                ),
                2,
            )
            step.summary = summary
            step.reasoning_source = reasoning_source
            step.observations = observations or []
            step.risks = risks or []
            step.downstream_impacts = downstream_impacts or []
            step.recommended_action_ids = recommended_action_ids or []
            step.tradeoffs = tradeoffs or []
            step.llm_used = llm_used
            step.llm_error = llm_error
            step.fallback_used = bool(llm_error)
            step.fallback_reason = llm_error
            step.output_snapshot = output_snapshot or {}
            return

    def _complete_agent_step(
        self, state: SystemState, node_key: str, output: AgentProposal
    ) -> None:
        summary = (
            output.domain_summary
            or output.notes_for_planner
            or "; ".join(output.observations[:2])
            or "node executed"
        )
        reasoning_source = (
            "ai_assisted_reasoning" if output.llm_used else "deterministic_or_fallback"
        )
        self._complete_step(
            state,
            node_key=node_key,
            summary=summary,
            reasoning_source=reasoning_source,
            observations=output.observations,
            risks=output.risks,
            downstream_impacts=output.downstream_impacts,
            recommended_action_ids=output.recommended_action_ids,
            tradeoffs=output.tradeoffs,
            llm_used=output.llm_used,
            llm_error=output.llm_error,
            output_snapshot={
                "proposal_count": len(output.proposals),
                "recommended_action_count": len(output.recommended_action_ids),
            },
        )

    def _record_route(
        self,
        state: SystemState,
        from_node: str,
        outcome: str,
        to_node: str,
        reason: str,
    ) -> None:
        if state.latest_trace is None:
            return
        state.latest_trace.route_decisions.append(
            TraceRouteDecision(
                from_node=from_node,
                outcome=outcome,
                to_node=to_node,
                reason=reason,
            )
        )

    def _update_trace_from_plan(self, state: SystemState) -> None:
        if state.latest_trace is None:
            return
        latest_decision = state.decision_logs[-1] if state.decision_logs else None
        state.latest_trace.selected_plan_id = state.latest_plan_id
        state.latest_trace.selected_strategy = (
            state.latest_plan.strategy_label if state.latest_plan else None
        )
        state.latest_trace.candidate_count = (
            len(latest_decision.candidate_evaluations) if latest_decision else 0
        )
        state.latest_trace.decision_id = (
            latest_decision.decision_id if latest_decision else None
        )
        state.latest_trace.selection_reason = (
            latest_decision.selection_reason if latest_decision else None
        )
        state.latest_trace.approval_pending = state.pending_plan is not None
        state.latest_trace.approval_reason = (
            latest_decision.approval_reason if latest_decision else ""
        )
        state.latest_trace.critic_summary = (
            latest_decision.critic_summary if latest_decision else None
        )

    def _risk_route_reason(self, outcome: str) -> str:
        if outcome == "approval":
            return "pending approval already exists or the system is already in approval mode"
        return f"dynamic routing assigned the next agent as {outcome}"

    def _critic_route_reason(self, state: SystemState, outcome: str) -> str:
        if outcome == "approval":
            return (
                state.latest_plan.approval_reason
                if state.latest_plan is not None
                else "selected plan requires approval"
            )
        return "selected plan cleared deterministic approval guardrails and can execute"

    def _handoff_reason(self, from_node: str, to_node: str) -> str:
        reasons = {
            (
                "demand",
                "inventory",
            ): "demand analysis updates forecast and hands replenishment to inventory planning",
            (
                "inventory",
                "planner",
            ): "inventory planning completed and handed feasible replenishment options to the planner",
            (
                "supplier",
                "logistics",
            ): "supplier mitigation options were prepared and routing alternatives are needed before final planning",
            (
                "supplier",
                "planner",
            ): "supplier review completed and the planner can evaluate the candidate actions",
            (
                "logistics",
                "supplier",
            ): "routing disruption analysis completed and supplier mitigation is needed before planning",
            (
                "logistics",
                "planner",
            ): "routing analysis completed and the planner can score the candidate actions",
        }
        return reasons.get(
            (from_node, to_node), f"{from_node} forwarded the workflow to {to_node}"
        )

    def _record_output(self, state: SystemState, output) -> None:
        state.agent_outputs[output.agent] = output
        state.candidate_actions.extend(output.proposals)

    def _finalize(self, state: SystemState, started_at: float) -> SystemState:
        state.timestamp = utc_now()
        state.kpis = recompute_kpis(state, recovery_speed=state.kpis.recovery_speed)
        state.kpis.decision_latency_ms = round(
            (time.perf_counter() - started_at) * 1000.0, 2
        )
        if state.latest_trace is not None:
            state.latest_trace.completed_at = state.timestamp
            state.latest_trace.mode_after = state.mode.value
            state.latest_trace.status = "completed"
        return state

    def _notify_trace_update(
        self,
        state: SystemState,
        trace_updater: Callable[[OrchestrationTrace], None] | None,
    ) -> None:
        if trace_updater and state.latest_trace:
            trace_updater(state.latest_trace)

    def risk_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        event = graph_state.get("event")
        trace_updater = graph_state.get("trace_updater")

        self._emit(
            graph_state,
            type="start",
            agent="risk",
            step="init",
            message="Starting orchestration cycle",
            data={
                "mode": state.mode.value,
                "pending_plan": state.pending_plan is not None,
            },
        )

        self._reset_cycle(state)
        self._begin_trace(state, event)
        self._start_step(state, "risk", "agent", event)
        self._notify_trace_update(state, trace_updater)

        if event is not None:
            if event.dedupe_key not in {
                item.dedupe_key for item in state.active_events
            }:
                state.active_events.append(event)

        # Step 1: Mode selection
        self._emit(
            graph_state,
            type="thinking",
            agent="risk",
            step="mode_selection",
            message=f"Selecting operating mode based on {len(state.active_events)} active events",
            data={"active_events": len(state.active_events)},
        )

        # Step 2: External API calls
        self._emit(
            graph_state,
            type="action",
            agent="risk",
            step="api_weather",
            message="Fetching external Weather API for disruption intel",
            data={"api": "weather", "endpoint": "/mock/weather"},
        )

        self._emit(
            graph_state,
            type="action",
            agent="risk",
            step="api_routes",
            message="Fetching external Routes API for transport status",
            data={"api": "routes", "endpoint": "/mock/routes"},
        )

        self._emit(
            graph_state,
            type="action",
            agent="risk",
            step="api_suppliers",
            message="Fetching external Suppliers API for supplier health",
            data={"api": "suppliers", "endpoint": "/mock/suppliers"},
        )

        # Step 3: LLM enrichment
        self._emit(
            graph_state,
            type="thinking",
            agent="risk",
            step="llm_enrichment",
            message="Calling LLM to synthesize risk assessment from API data",
            data={"capability": "specialist", "purpose": "domain_summary_generation"},
        )

        max_sev = max((e.severity for e in state.active_events), default=0.0)
        output = self.risk_agent.run(state, event)
        self._record_output(state, output)
        self._complete_agent_step(state, "risk", output)

        # Step 4: Results
        self._emit(
            graph_state,
            type="observation",
            agent="risk",
            step="results",
            message=f"Risk assessment complete — {len(output.proposals)} mitigations proposed",
            data={
                "proposals": len(output.proposals),
                "llm_used": output.llm_used,
                "llm_error": output.llm_error,
                "mode": state.mode.value,
                "max_severity": round(max_sev, 2),
                "domain_summary": (output.domain_summary or "")[:200],
            },
        )

        risk_route = route_after_risk({"state": state})
        self._emit(
            graph_state,
            type="decision",
            agent="risk",
            step="routing",
            message=f"Next routing → {risk_route}",
            data={
                "next_node": risk_route,
                "reason": self._risk_route_reason(risk_route),
            },
        )

        self._record_route(
            state,
            "risk",
            risk_route,
            risk_route,
            self._risk_route_reason(risk_route),
        )
        if state.latest_trace is not None:
            state.latest_trace.current_branch = state.mode.value

        self._notify_trace_update(state, trace_updater)
        return {
            "state": state,
            "event": event,
            "started_at": graph_state["started_at"],
            "run_id": graph_state.get("run_id"),
            "trace_updater": trace_updater,
        }

    def demand_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        event = graph_state.get("event")
        trace_updater = graph_state.get("trace_updater")
        scope = resolve_scenario_scope(state, event)

        sku_count = len(state.inventory)
        self._emit(
            graph_state,
            type="start",
            agent="demand",
            step="init",
            message=f"Demand Agent beginning forecast analysis for {sku_count} SKUs",
            data={"sku_count": sku_count},
        )

        self._start_step(state, "demand", "agent", event)
        self._notify_trace_update(state, trace_updater)

        # Step 1: Check for demand spike event
        has_spike = event and event.type.value in {"demand_spike", "compound"}
        if has_spike:
            demand_changes = scope.demand_changes
            if demand_changes:
                sku_list = [str(item["sku"]) for item in demand_changes]
                preview = ", ".join(sku_list[:3])
                self._emit(
                    graph_state,
                    type="analysis",
                    agent="demand",
                    step="spike_detection",
                    message=f"Demand spike detected across {len(sku_list)} SKUs: {preview}",
                    data={"affected_skus": sku_list, "demand_changes": demand_changes},
                )
            else:
                multiplier = event.payload.get("multiplier", 1.5)
                spike_sku = event.payload.get("sku")
                self._emit(
                    graph_state,
                    type="analysis",
                    agent="demand",
                    step="spike_detection",
                    message=f"Demand spike detected: SKU {spike_sku} at {multiplier}x multiplier",
                    data={"spike_sku": spike_sku, "multiplier": multiplier},
                )
        else:
            self._emit(
                graph_state,
                type="analysis",
                agent="demand",
                step="routine_forecast",
                message="No demand spike — running routine 30-day rolling forecast",
                data={"method": "rolling_average_30d"},
            )

        # Step 2: Statistical computation
        self._emit(
            graph_state,
            type="thinking",
            agent="demand",
            step="statistics",
            message="Computing per-SKU average demand, standard deviation, and forecast adjustments",
            data={"method": "pandas_rolling_stats", "window": 30},
        )

        output = self.demand_agent.run(state, event)
        self._record_output(state, output)
        self._complete_agent_step(state, "demand", output)

        # Step 3: LLM enrichment (if triggered)
        if output.llm_used:
            self._emit(
                graph_state,
                type="observation",
                agent="demand",
                step="llm_result",
                message="LLM enriched demand summary with contextual analysis",
                data={
                    "llm_used": True,
                    "domain_summary": (output.domain_summary or "")[:200],
                },
            )
        else:
            self._emit(
                graph_state,
                type="observation",
                agent="demand",
                step="deterministic_result",
                message="Demand analysis completed using deterministic forecasting",
                data={
                    "llm_used": False,
                    "llm_error": output.llm_error,
                    "proposals": len(output.proposals),
                    "observations": output.observations[:3],
                },
            )

        next_node = route_after_demand({"state": state})
        self._emit(
            graph_state,
            type="decision",
            agent="demand",
            step="routing",
            message=f"Demand analysis completed — routing to {next_node}",
            data={"next_node": next_node, "proposals": len(output.proposals)},
        )

        self._record_route(
            state,
            "demand",
            next_node,
            next_node,
            self._handoff_reason("demand", next_node),
        )
        self._notify_trace_update(state, trace_updater)
        return {**graph_state, "run_id": graph_state.get("run_id")}

    def inventory_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        event = graph_state.get("event")
        trace_updater = graph_state.get("trace_updater")

        # Step 1: Initial scan
        scope = resolve_scenario_scope(state, event)
        inventory_focus = set(scope.affected_skus)
        scoped_items = [
            item
            for sku, item in state.inventory.items()
            if not inventory_focus or sku in inventory_focus
        ]
        critical_skus = sum(
            1
            for item in scoped_items
            if item.on_hand + item.incoming_qty - item.forecast_qty < item.reorder_point
        )
        below_safety = sum(
            1
            for item in scoped_items
            if item.on_hand + item.incoming_qty - item.forecast_qty < item.safety_stock
        )
        self._emit(
            graph_state,
            type="start",
            agent="inventory",
            step="init",
            message=f"Inventory Agent checking {len(state.inventory)} SKUs",
            data={
                "sku_count": len(scoped_items),
                "critical_skus": critical_skus,
                "below_safety": below_safety,
                "direct_scope_skus": len(inventory_focus),
            },
        )

        self._start_step(state, "inventory", "agent", event)
        self._notify_trace_update(state, trace_updater)

        # Step 2: Computational analysis
        self._emit(
            graph_state,
            type="thinking",
            agent="inventory",
            step="rop_calculation",
            message="Computing Reorder Point (ROP), Safety Stock (SS), and Days of Cover for each SKU",
            data={
                "method": "z_score_based_safety_stock",
                "formula": "ROP = LTD + z * σ * √LT",
            },
        )

        self._emit(
            graph_state,
            type="thinking",
            agent="inventory",
            step="replenishment_check",
            message="Identifying SKUs that need replenishment by comparing projected stock vs ROP",
            data={"comparison": "projected_stock < reorder_point"},
        )

        output = self.inventory_agent.run(state, event)
        self._record_output(state, output)
        self._complete_agent_step(state, "inventory", output)

        # Step 3: Results
        reorder_count = len(output.proposals)
        if output.llm_used:
            self._emit(
                graph_state,
                type="observation",
                agent="inventory",
                step="llm_result",
                message=f"LLM enriched inventory analysis — {reorder_count} reorder proposals generated",
                data={
                    "llm_used": True,
                    "reorder_proposals": reorder_count,
                    "domain_summary": (output.domain_summary or "")[:200],
                },
            )
        else:
            self._emit(
                graph_state,
                type="observation",
                agent="inventory",
                step="results",
                message=f"Inventory analysis complete — {reorder_count} reorder proposals, {below_safety} SKUs below safety stock",
                data={
                    "llm_used": False,
                    "llm_error": output.llm_error,
                    "reorder_proposals": reorder_count,
                    "below_safety": below_safety,
                    "observations": output.observations[:3],
                },
            )

        next_node = route_after_inventory({"state": state})
        self._emit(
            graph_state,
            type="decision",
            agent="inventory",
            step="routing",
            message=f"Inventory planning done — routing to {next_node}",
            data={"next_node": next_node},
        )

        self._record_route(
            state,
            "inventory",
            next_node,
            next_node,
            self._handoff_reason("inventory", next_node),
        )
        self._notify_trace_update(state, trace_updater)
        return {**graph_state, "run_id": graph_state.get("run_id")}

    def supplier_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        event = graph_state.get("event")
        trace_updater = graph_state.get("trace_updater")

        supplier_count = len(state.suppliers)
        scope = resolve_scenario_scope(state, event)
        self._emit(
            graph_state,
            type="start",
            agent="supplier",
            step="init",
            message=f"Supplier Agent evaluating {supplier_count} suppliers",
            data={"supplier_count": supplier_count},
        )

        self._start_step(state, "supplier", "agent", event)
        self._notify_trace_update(state, trace_updater)

        # Step 1: Detecting delayed suppliers
        delayed_suppliers = scope.supplier_ids
        if delayed_suppliers:
            self._emit(
                graph_state,
                type="analysis",
                agent="supplier",
                step="delay_detection",
                message=f"Supplier disruption detected across {len(delayed_suppliers)} supplier(s) impacting {len(scope.supplier_affected_skus or scope.affected_skus)} SKU(s)",
                data={
                    "delayed_suppliers": delayed_suppliers,
                    "event_type": event.type.value,
                    "affected_skus": scope.supplier_affected_skus or scope.affected_skus,
                },
            )
        else:
            self._emit(
                graph_state,
                type="analysis",
                agent="supplier",
                step="routine_eval",
                message="No supplier disruption — running routine supplier ranking",
                data={"method": "reliability_cost_leadtime_sort"},
            )

        # Step 2: Ranking and switching
        self._emit(
            graph_state,
            type="thinking",
            agent="supplier",
            step="ranking",
            message="Ranking suppliers by reliability, unit cost, and lead time for each SKU",
            data={"criteria": ["reliability", "unit_cost", "lead_time_days"]},
        )

        output = self.supplier_agent.run(state, event)
        self._record_output(state, output)
        self._complete_agent_step(state, "supplier", output)

        # Step 3: Results
        if output.llm_used:
            self._emit(
                graph_state,
                type="observation",
                agent="supplier",
                step="llm_result",
                message=f"LLM enriched supplier analysis — {len(output.proposals)} switch proposals",
                data={
                    "llm_used": True,
                    "proposals": len(output.proposals),
                    "domain_summary": (output.domain_summary or "")[:200],
                },
            )
        else:
            self._emit(
                graph_state,
                type="observation",
                agent="supplier",
                step="results",
                message=f"Supplier Agent proposed {len(output.proposals)} supplier switches",
                data={
                    "llm_used": False,
                    "llm_error": output.llm_error,
                    "proposals": len(output.proposals),
                    "observations": output.observations[:3],
                },
            )

        next_node = route_after_supplier({"state": state})
        self._emit(
            graph_state,
            type="decision",
            agent="supplier",
            step="routing",
            message=f"Supplier evaluation done — routing to {next_node}",
            data={"next_node": next_node},
        )

        self._record_route(
            state,
            "supplier",
            next_node,
            next_node,
            self._handoff_reason("supplier", next_node),
        )
        self._notify_trace_update(state, trace_updater)
        return {**graph_state, "run_id": graph_state.get("run_id")}

    def logistics_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        event = graph_state.get("event")
        trace_updater = graph_state.get("trace_updater")

        route_count = len(state.routes)
        scope = resolve_scenario_scope(state, event)
        self._emit(
            graph_state,
            type="start",
            agent="logistics",
            step="init",
            message=f"Logistics Agent checking {route_count} transport routes",
            data={"route_count": route_count},
        )

        self._start_step(state, "logistics", "agent", event)
        self._notify_trace_update(state, trace_updater)

        # Step 1: Route blockage detection
        blocked_routes = scope.route_ids
        if blocked_routes:
            self._emit(
                graph_state,
                type="analysis",
                agent="logistics",
                step="blockage_detection",
                message=f"Route blockage detected across {len(blocked_routes)} lane(s) affecting {len(scope.route_affected_skus)} SKU(s)",
                data={
                    "blocked_routes": blocked_routes,
                    "affected_skus": scope.route_affected_skus,
                    "warehouse_ids": scope.warehouse_ids,
                    "node_ids": scope.node_ids,
                    "reason": event.payload.get("reason", "unknown"),
                },
            )
        else:
            self._emit(
                graph_state,
                type="analysis",
                agent="logistics",
                step="routine_check",
                message="No route blockage — optimizing transport routes",
                data={"method": "risk_transit_cost_sort"},
            )

        # Step 2: Route ranking
        available = sum(1 for r in state.routes.values() if r.status != "blocked")
        self._emit(
            graph_state,
            type="thinking",
            agent="logistics",
            step="route_ranking",
            message=f"Ranking {available} available routes by risk score, transit time, and cost",
            data={
                "available_routes": available,
                "criteria": ["risk_score", "transit_days", "cost"],
            },
        )

        output = self.logistics_agent.run(state, event)
        self._record_output(state, output)
        self._complete_agent_step(state, "logistics", output)

        # Step 3: Results
        if output.llm_used:
            self._emit(
                graph_state,
                type="observation",
                agent="logistics",
                step="llm_result",
                message=f"LLM enriched logistics analysis — {len(output.proposals)} reroute proposals",
                data={
                    "llm_used": True,
                    "proposals": len(output.proposals),
                    "domain_summary": (output.domain_summary or "")[:200],
                },
            )
        else:
            self._emit(
                graph_state,
                type="observation",
                agent="logistics",
                step="results",
                message=f"Logistics Agent proposed {len(output.proposals)} reroute actions",
                data={
                    "llm_used": False,
                    "llm_error": output.llm_error,
                    "proposals": len(output.proposals),
                    "observations": output.observations[:3],
                },
            )

        next_node = route_after_logistics({"state": state})
        self._emit(
            graph_state,
            type="decision",
            agent="logistics",
            step="routing",
            message=f"Logistics planning done — routing to {next_node}",
            data={"next_node": next_node},
        )

        self._record_route(
            state,
            "logistics",
            next_node,
            next_node,
            self._handoff_reason("logistics", next_node),
        )
        self._notify_trace_update(state, trace_updater)
        return {**graph_state, "run_id": graph_state.get("run_id")}

    def planner_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        event = graph_state.get("event")
        trace_updater = graph_state.get("trace_updater")

        candidate_count = len(state.candidate_actions)
        self._emit(
            graph_state,
            type="start",
            agent="planner",
            step="init",
            message=f"Planner starting with {candidate_count} candidate actions from specialist agents",
            data={"candidate_actions": candidate_count, "mode": state.mode.value},
        )

        self._start_step(state, "planner", "agent", event)
        self._notify_trace_update(state, trace_updater)

        # Step 1: Feasibility filtering
        self._emit(
            graph_state,
            type="thinking",
            agent="planner",
            step="feasibility_filter",
            message="Filtering candidate actions through hard constraints",
            data={
                "method": "evaluate_hard_constraints",
                "input_count": candidate_count,
            },
        )

        # Step 2: Strategy generation
        self._emit(
            graph_state,
            type="thinking",
            agent="planner",
            step="strategy_generation",
            message="Generating 3 strategies: cost_first, balanced, resilience_first",
            data={"strategies": ["cost_first", "balanced", "resilience_first"]},
        )

        # Step 3: LLM or deterministic
        self._emit(
            graph_state,
            type="action",
            agent="planner",
            step="candidate_drafting",
            message="Calling LLM to draft candidate plans (falling back to deterministic if unavailable)",
            data={"capability": "planner", "fallback": "deterministic_sort"},
        )

        # Step 4: Simulation
        self._emit(
            graph_state,
            type="thinking",
            agent="planner",
            step="simulation",
            message="Running multi-horizon simulations for each strategy to project KPIs",
            data={
                "method": "evaluate_candidate_plan",
                "metrics": [
                    "service_level",
                    "cost",
                    "disruption_risk",
                    "recovery_speed",
                ],
            },
        )

        output = self.planner_agent.run(state, event)
        self._record_output(state, output)
        self._update_trace_from_plan(state)
        latest_decision = state.decision_logs[-1] if state.decision_logs else None
        self._complete_step(
            state,
            node_key="planner",
            summary=output.notes_for_planner
            or output.domain_summary
            or "planner generated candidate plans",
            reasoning_source="ai_assisted_reasoning"
            if output.llm_used
            else "deterministic_or_fallback",
            observations=output.observations,
            risks=output.risks,
            downstream_impacts=output.downstream_impacts,
            recommended_action_ids=output.recommended_action_ids,
            tradeoffs=output.tradeoffs,
            llm_used=output.llm_used,
            llm_error=output.llm_error,
            output_snapshot={
                "selected_plan_id": state.latest_plan_id,
                "selected_strategy": state.latest_plan.strategy_label
                if state.latest_plan
                else None,
                "generated_by": state.latest_plan.generated_by
                if state.latest_plan
                else None,
                "candidate_count": len(latest_decision.candidate_evaluations)
                if latest_decision
                else 0,
                "approval_required": state.latest_plan.approval_required
                if state.latest_plan
                else False,
                "simulation_horizon_days": (
                    latest_decision.candidate_evaluations[0].simulation_horizon_days
                    if latest_decision and latest_decision.candidate_evaluations
                    else 0
                ),
                "projection_summary": (
                    next(
                        (
                            item.projection_summary
                            for item in latest_decision.candidate_evaluations
                            if item.strategy_label == state.latest_plan.strategy_label
                        ),
                        "",
                    )
                    if latest_decision and state.latest_plan
                    else ""
                ),
                "projection_steps": (
                    [
                        {
                            "label": step.label,
                            "service_level": step.kpis.service_level,
                            "disruption_risk": step.kpis.disruption_risk,
                            "recovery_speed": step.kpis.recovery_speed,
                            "inventory_at_risk": step.inventory_at_risk,
                            "inventory_out_of_stock": step.inventory_out_of_stock,
                            "backlog_units": step.backlog_units,
                            "summary": step.summary,
                        }
                        for item in latest_decision.candidate_evaluations
                        if state.latest_plan
                        and item.strategy_label == state.latest_plan.strategy_label
                        for step in item.projection_steps
                    ]
                    if latest_decision and state.latest_plan
                    else []
                ),
            },
        )

        # Step 5: Report results
        if state.latest_plan is not None:
            generated_by = state.latest_plan.generated_by or "unknown"
            self._emit(
                graph_state,
                type="observation",
                agent="planner",
                step="generation_method",
                message=f"Plan generated by: {generated_by}",
                data={
                    "generated_by": generated_by,
                    "llm_used": output.llm_used,
                    "llm_error": output.llm_error,
                },
            )

            self._emit(
                graph_state,
                type="decision",
                agent="planner",
                step="plan_selected",
                message=f"Selected strategy '{state.latest_plan.strategy_label or 'unknown'}' "
                f"(score={state.latest_plan.score:.3f})",
                data={
                    "plan_id": state.latest_plan.plan_id,
                    "strategy": state.latest_plan.strategy_label,
                    "score": round(state.latest_plan.score, 4),
                    "approval_required": state.latest_plan.approval_required,
                    "action_count": len(state.latest_plan.actions),
                },
            )
        self._record_route(
            state,
            "planner",
            "critic",
            "critic",
            "planner always forwards candidate plans to the critic",
        )
        self._notify_trace_update(state, trace_updater)
        return {**graph_state, "run_id": graph_state.get("run_id")}

    def critic_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        event = graph_state.get("event")
        trace_updater = graph_state.get("trace_updater")

        plan_label = (
            state.latest_plan.strategy_label if state.latest_plan else "unknown"
        )
        self._emit(
            graph_state,
            type="start",
            agent="critic",
            step="init",
            message=f"Critic starting review of plan '{plan_label}'",
            data={
                "plan_id": state.latest_plan.plan_id if state.latest_plan else None,
                "strategy": plan_label,
                "action_count": len(state.latest_plan.actions)
                if state.latest_plan
                else 0,
            },
        )

        self._start_step(state, "critic", "agent", event)
        self._notify_trace_update(state, trace_updater)

        # Step 1: LLM critique
        self._emit(
            graph_state,
            type="action",
            agent="critic",
            step="llm_critique",
            message="Calling LLM to critique the selected plan against alternatives",
            data={"capability": "critic", "purpose": "plan_review_and_findings"},
        )

        output = self.critic_agent.run(state, event)
        state.agent_outputs[output.agent] = output
        self._complete_step(
            state,
            node_key="critic",
            summary=output.domain_summary
            or output.notes_for_planner
            or "critic reviewed the selected plan",
            reasoning_source="ai_assisted_reasoning"
            if output.llm_used
            else "deterministic_or_fallback",
            observations=output.observations,
            risks=output.risks,
            downstream_impacts=output.downstream_impacts,
            recommended_action_ids=output.recommended_action_ids,
            tradeoffs=output.tradeoffs,
            llm_used=output.llm_used,
            llm_error=output.llm_error,
            output_snapshot={
                "critic_summary": state.decision_logs[-1].critic_summary
                if state.decision_logs
                else None,
                "finding_count": len(state.decision_logs[-1].critic_findings)
                if state.decision_logs
                else 0,
            },
        )

        # Step 2: Report results
        critic_route = route_after_critic({"state": state})
        finding_count = (
            len(state.decision_logs[-1].critic_findings) if state.decision_logs else 0
        )
        critic_summary = (
            state.decision_logs[-1].critic_summary
            if state.decision_logs
            else "no findings"
        )

        if output.llm_used:
            self._emit(
                graph_state,
                type="observation",
                agent="critic",
                step="llm_result",
                message=f"LLM critique completed — {finding_count} finding(s)",
                data={
                    "llm_used": True,
                    "finding_count": finding_count,
                    "critic_summary": (critic_summary or "")[:200],
                },
            )
        else:
            self._emit(
                graph_state,
                type="observation",
                agent="critic",
                step="deterministic_result",
                message=f"Deterministic review completed — {finding_count} finding(s)",
                data={
                    "llm_used": False,
                    "llm_error": output.llm_error,
                    "finding_count": finding_count,
                    "critic_summary": (critic_summary or "")[:200],
                },
            )

        self._emit(
            graph_state,
            type="decision",
            agent="critic",
            step="routing",
            message=f"Critic routing → {critic_route}",
            data={
                "next_node": critic_route,
                "reason": self._critic_route_reason(state, critic_route),
                "approval_required": state.latest_plan.approval_required
                if state.latest_plan
                else False,
            },
        )
        self._record_route(
            state,
            "critic",
            critic_route,
            critic_route,
            self._critic_route_reason(state, critic_route),
        )
        self._notify_trace_update(state, trace_updater)
        return {**graph_state, "run_id": graph_state.get("run_id")}

    def approval_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        event = graph_state.get("event")
        trace_updater = graph_state.get("trace_updater")

        approval_reason = (
            state.latest_plan.approval_reason
            if state.latest_plan
            else "approval required"
        )
        decision_id = (
            state.decision_logs[-1].decision_id if state.decision_logs else None
        )

        self._emit(
            graph_state,
            type="decision",
            agent="system",
            step="approval_gate",
            message=f"Plan awaiting manual approval: {approval_reason}",
            data={"reason": approval_reason, "decision_id": decision_id},
        )

        self._start_step(state, "approval", "gate", event)
        self._notify_trace_update(state, trace_updater)

        state.mode = Mode.APPROVAL
        self._update_trace_from_plan(state)
        if state.latest_trace is not None:
            state.latest_trace.terminal_stage = "approval"
            state.latest_trace.execution_status = "pending_approval"
            state.latest_trace.approval_pending = True

        self._complete_step(
            state,
            node_key="approval",
            summary=approval_reason,
            reasoning_source="deterministic_policy_guardrail",
            output_snapshot={
                "decision_id": decision_id,
                "approval_required": True,
                "approval_status": state.decision_logs[-1].approval_status.value
                if state.decision_logs
                else None,
            },
        )
        state = self._finalize(state, graph_state["started_at"])

        self._emit(
            graph_state,
            type="final",
            agent="system",
            step="complete",
            message="Orchestration complete — plan awaiting approval",
            data={
                "execution_status": "pending_approval",
                "plan_id": state.latest_plan.plan_id if state.latest_plan else None,
                "mode": state.mode.value,
            },
        )
        self._notify_trace_update(state, trace_updater)
        return {
            "state": state,
            "event": event,
            "started_at": graph_state["started_at"],
            "run_id": graph_state.get("run_id"),
            "trace_updater": trace_updater,
        }

    def execution_node(self, graph_state: OrchestrationState) -> OrchestrationState:
        state = graph_state["state"]
        event = graph_state.get("event")
        trace_updater = graph_state.get("trace_updater")

        plan_id = state.latest_plan.plan_id if state.latest_plan else None
        self._emit(
            graph_state,
            type="action",
            agent="system",
            step="execute",
            message=f"Executing plan '{plan_id or 'N/A'}'",
            data={
                "plan_id": plan_id,
                "action_count": len(state.latest_plan.actions)
                if state.latest_plan
                else 0,
            },
        )

        self._start_step(state, "execution", "execution", event)
        self._notify_trace_update(state, trace_updater)

        execution_summary = "no plan executed"
        execution_status = "no_op"
        if state.latest_plan and not state.latest_plan.approval_required:
            state.latest_plan.status = PlanStatus.APPLIED
            state = apply_plan(state, state.latest_plan)
            if state.decision_logs:
                state.decision_logs[-1].approval_status = ApprovalStatus.AUTO_APPLIED
            state.mode = Mode.CRISIS if event and state.active_events else Mode.NORMAL
            execution_summary = (
                f"Applied {state.latest_plan.plan_id} using "
                f"{state.latest_plan.strategy_label or 'unlabeled'} strategy"
            )
            execution_status = "auto_applied"

        self._update_trace_from_plan(state)
        if state.latest_trace is not None:
            state.latest_trace.terminal_stage = "execution"
            state.latest_trace.execution_status = execution_status
            state.latest_trace.approval_pending = False

        self._complete_step(
            state,
            node_key="execution",
            summary=execution_summary,
            reasoning_source="deterministic_execution_guard",
            output_snapshot={
                "execution_status": execution_status,
                "latest_plan_id": state.latest_plan_id,
                "mode_after_execution": state.mode.value,
            },
        )
        state = self._finalize(state, graph_state["started_at"])

        self._emit(
            graph_state,
            type="final",
            agent="system",
            step="complete",
            message=f"Orchestration complete — {execution_status}",
            data={
                "execution_status": execution_status,
                "plan_id": state.latest_plan_id,
                "mode": state.mode.value,
            },
        )
        self._notify_trace_update(state, trace_updater)
        return {
            "state": state,
            "event": event,
            "started_at": graph_state["started_at"],
            "run_id": graph_state.get("run_id"),
            "trace_updater": trace_updater,
        }

    def _compile(self):
        graph = StateGraph(OrchestrationState)
        graph.add_node("risk", self.risk_node)
        graph.add_node("demand", self.demand_node)
        graph.add_node("inventory", self.inventory_node)
        graph.add_node("supplier", self.supplier_node)
        graph.add_node("logistics", self.logistics_node)
        graph.add_node("planner", self.planner_node)
        graph.add_node("critic", self.critic_node)
        graph.add_node("approval", self.approval_node)
        graph.add_node("execution", self.execution_node)

        graph.add_edge(START, "risk")
        graph.add_conditional_edges(
            "risk",
            route_after_risk,
            {
                "logistics": "logistics",
                "supplier": "supplier",
                "demand": "demand",
                "planner": "planner",
                "approval": "approval",
            },
        )
        graph.add_conditional_edges(
            "logistics",
            route_after_logistics,
            {
                "inventory": "inventory",
                "supplier": "supplier",
                "planner": "planner",
            },
        )
        graph.add_conditional_edges(
            "supplier",
            route_after_supplier,
            {
                "demand": "demand",
                "inventory": "inventory",
                "logistics": "logistics",
                "planner": "planner",
            },
        )
        graph.add_conditional_edges(
            "demand",
            route_after_demand,
            {
                "inventory": "inventory",
            },
        )
        graph.add_conditional_edges(
            "inventory",
            route_after_inventory,
            {
                "planner": "planner",
            },
        )
        graph.add_conditional_edges(
            "planner",
            route_after_planner,
            {
                "critic": "critic",
            },
        )
        graph.add_conditional_edges(
            "critic",
            route_after_critic,
            {
                "approval": "approval",
                "execution": "execution",
            },
        )
        graph.add_edge("approval", END)
        graph.add_edge("execution", END)
        return graph.compile()

    def invoke(
        self,
        state: SystemState,
        event: Event | None = None,
        run_id: str | None = None,
        trace_updater: Callable[[OrchestrationTrace], None] | None = None,
    ) -> SystemState:
        state.run_id = run_id or new_run_id()
        result = self.graph.invoke(
            {
                "state": state,
                "event": event,
                "started_at": time.perf_counter(),
                "run_id": state.run_id,
                "trace_updater": trace_updater,
            }
        )
        return result["state"]


def build_graph() -> LangGraphControlTower:
    return LangGraphControlTower()
