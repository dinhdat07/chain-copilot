from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from core.enums import ApprovalStatus
from core.memory import SQLiteStore
from core.models import Action, DecisionLog, Event, Plan, SystemState
from core.state import clone_state, load_initial_state, recompute_kpis, state_summary, utc_now
from orchestrator.graph import build_graph
from orchestrator.service import (
    PendingApprovalError,
    approve_pending_plan,
    request_safer_plan,
    reset_runtime,
    run_daily_plan,
)
from simulation.runner import ScenarioRunner
from simulation.scenarios import get_scenario_events, list_scenarios

from app_api.schemas import (
    ActionView,
    AgentStepView,
    AlertView,
    CandidateEvaluationView,
    ControlTowerStateResponse,
    ControlTowerSummaryResponse,
    DecisionLogDetailView,
    DecisionLogSummaryView,
    EventView,
    InventoryRowView,
    KPIView,
    PendingApprovalView,
    PlanView,
    ReflectionView,
    RouteDecisionView,
    ScenarioOutcomeView,
    SupplierRowView,
    TraceView,
)


def _error_detail(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "details": details or {},
        "retryable": retryable,
    }


def raise_not_found(resource: str, resource_id: str) -> None:
    raise HTTPException(
        status_code=404,
        detail=_error_detail(
            code=f"{resource}_not_found",
            message=f"{resource} not found",
            details={"id": resource_id},
        ),
    )


def raise_conflict(message: str, *, code: str = "invalid_state") -> None:
    raise HTTPException(
        status_code=409,
        detail=_error_detail(code=code, message=message, retryable=False),
    )


@dataclass
class ControlTowerRuntime:
    store: SQLiteStore
    state: SystemState
    graph: Any
    runner: ScenarioRunner

    @classmethod
    def create(cls, store: SQLiteStore | None = None) -> "ControlTowerRuntime":
        local_store = store or SQLiteStore()
        return cls(
            store=local_store,
            state=load_initial_state(),
            graph=build_graph(),
            runner=ScenarioRunner(store=local_store),
        )

    def reinitialize(self, store: SQLiteStore | None = None) -> None:
        self.store = store or self.store
        self.state = load_initial_state()
        self.graph = build_graph()
        self.runner = ScenarioRunner(store=self.store)

    def reset(self) -> SystemState:
        self.state = reset_runtime(self.store)
        self.graph = build_graph()
        self.runner = ScenarioRunner(store=self.store)
        return self.state

    def current_decision_id(self) -> str | None:
        if not self.state.decision_logs:
            return None
        return self.state.decision_logs[-1].decision_id

    def legacy_response_payload(self) -> dict[str, Any]:
        return {
            "summary": state_summary(self.state),
            "latest_plan": self.state.latest_plan.model_dump(mode="json") if self.state.latest_plan else None,
            "pending_plan": self.state.pending_plan.model_dump(mode="json") if self.state.pending_plan else None,
            "decision_id": self.current_decision_id(),
        }

    def run_daily(self) -> SystemState:
        try:
            self.state = run_daily_plan(self.state, self.store, graph=self.graph)
        except PendingApprovalError as exc:
            raise_conflict(str(exc), code="pending_approval")
        return self.state

    def ingest_event(self, event: Event) -> SystemState:
        self.state = self.graph.invoke(self.state, event)
        self.store.save_state(self.state)
        if self.state.decision_logs:
            self.store.save_decision_log(self.state.decision_logs[-1])
        return self.state

    def run_scenario(self, scenario_name: str, seed: int) -> SystemState:
        if scenario_name not in list_scenarios():
            raise_not_found("scenario", scenario_name)
        try:
            self.state = self.runner.run(self.state, scenario_name, seed=seed)
        except PendingApprovalError as exc:
            raise_conflict(str(exc), code="pending_approval")
        return self.state

    def approval_command(self, decision_id: str, action: str) -> SystemState:
        try:
            if action == "approve":
                self.state = approve_pending_plan(self.state, self.store, decision_id, True)
            elif action == "reject":
                self.state = approve_pending_plan(self.state, self.store, decision_id, False)
            elif action == "safer_plan":
                self.state = request_safer_plan(self.state, self.store, decision_id)
            else:
                raise HTTPException(
                    status_code=422,
                    detail=_error_detail(
                        code="invalid_approval_action",
                        message="approval action must be approve, reject, or safer_plan",
                    ),
                )
        except ValueError as exc:
            raise_not_found("decision", decision_id)
        return self.state

    def what_if(self, scenario_name: str, seed: int) -> dict[str, Any]:
        del seed
        if scenario_name not in list_scenarios():
            raise_not_found("scenario", scenario_name)
        simulated = clone_state(self.state)
        for event in get_scenario_events(scenario_name):
            simulated = self.graph.invoke(simulated, event)
        return {
            "scenario_name": scenario_name,
            "summary": state_summary(simulated),
            "latest_plan": simulated.latest_plan.model_dump(mode="json") if simulated.latest_plan else None,
        }


def make_runtime(store: SQLiteStore | None = None) -> ControlTowerRuntime:
    return ControlTowerRuntime.create(store=store)


def kpi_view(kpis) -> KPIView:
    return KPIView(**kpis.model_dump())


def action_view(action: Action) -> ActionView:
    return ActionView(
        action_id=action.action_id,
        action_type=action.action_type.value,
        target_id=action.target_id,
        reason=action.reason,
        priority=action.priority,
        estimated_cost_delta=action.estimated_cost_delta,
        estimated_service_delta=action.estimated_service_delta,
        estimated_risk_delta=action.estimated_risk_delta,
        estimated_recovery_hours=action.estimated_recovery_hours,
        parameters=action.parameters,
    )


def plan_view(plan: Plan | None) -> PlanView | None:
    if plan is None:
        return None
    return PlanView(
        plan_id=plan.plan_id,
        mode=plan.mode.value,
        status=plan.status.value,
        score=plan.score,
        score_breakdown=plan.score_breakdown,
        strategy_label=plan.strategy_label,
        generated_by=plan.generated_by,
        approval_required=plan.approval_required,
        approval_reason=plan.approval_reason,
        planner_reasoning=plan.planner_reasoning,
        llm_planner_narrative=plan.llm_planner_narrative,
        critic_summary=plan.critic_summary,
        trigger_event_ids=plan.trigger_event_ids,
        actions=[action_view(item) for item in plan.actions],
    )


def event_view(event: Event) -> EventView:
    return EventView(
        event_id=event.event_id,
        type=event.type.value,
        severity=event.severity,
        source=event.source,
        entity_ids=event.entity_ids,
        occurred_at=event.occurred_at,
        detected_at=event.detected_at,
        payload=event.payload,
    )


def candidate_evaluation_view(item) -> CandidateEvaluationView:
    return CandidateEvaluationView(
        strategy_label=item.strategy_label,
        action_ids=item.action_ids,
        score=item.score,
        score_breakdown=item.score_breakdown,
        projected_kpis=kpi_view(item.projected_kpis),
        approval_required=item.approval_required,
        approval_reason=item.approval_reason,
        rationale=item.rationale,
        llm_used=item.llm_used,
    )


def decision_summary_view(item: DecisionLog) -> DecisionLogSummaryView:
    return DecisionLogSummaryView(
        decision_id=item.decision_id,
        plan_id=item.plan_id,
        approval_status=item.approval_status.value,
        approval_required=item.approval_required,
        approval_reason=item.approval_reason,
        selection_reason=item.selection_reason,
        selected_actions=item.selected_actions,
        event_ids=item.event_ids,
        llm_used=item.llm_used,
    )


def decision_detail_view(item: DecisionLog) -> DecisionLogDetailView:
    return DecisionLogDetailView(
        decision_id=item.decision_id,
        plan_id=item.plan_id,
        approval_status=item.approval_status.value,
        approval_required=item.approval_required,
        approval_reason=item.approval_reason,
        rationale=item.rationale,
        selection_reason=item.selection_reason,
        winning_factors=item.winning_factors,
        score_breakdown=item.score_breakdown,
        selected_actions=item.selected_actions,
        rejected_actions=item.rejected_actions,
        candidate_evaluations=[candidate_evaluation_view(eval_item) for eval_item in item.candidate_evaluations],
        critic_summary=item.critic_summary,
        critic_findings=item.critic_findings,
        llm_used=item.llm_used,
        llm_provider=item.llm_provider,
        llm_model=item.llm_model,
        llm_error=item.llm_error,
        before_kpis=kpi_view(item.before_kpis),
        after_kpis=kpi_view(item.after_kpis),
    )


def _inventory_status(item) -> str:
    available = item.on_hand + item.incoming_qty
    if available <= 0:
        return "out_of_stock"
    if available <= item.reorder_point:
        return "low"
    if available <= item.safety_stock:
        return "at_risk"
    return "in_stock"


def inventory_rows(state: SystemState, *, search: str | None = None, status: str | None = None) -> list[InventoryRowView]:
    needle = (search or "").strip().lower()
    status_filter = (status or "").strip().lower()
    rows: list[InventoryRowView] = []
    for item in state.inventory.values():
        item_status = _inventory_status(item)
        if needle and needle not in item.sku.lower() and needle not in item.preferred_supplier_id.lower():
            continue
        if status_filter and item_status != status_filter:
            continue
        rows.append(
            InventoryRowView(
                sku=item.sku,
                warehouse_id=item.warehouse_id,
                on_hand=item.on_hand,
                incoming_qty=item.incoming_qty,
                forecast_qty=item.forecast_qty,
                reorder_point=item.reorder_point,
                safety_stock=item.safety_stock,
                unit_cost=item.unit_cost,
                status=item_status,
                preferred_supplier_id=item.preferred_supplier_id,
                preferred_route_id=item.preferred_route_id,
            )
        )
    rows.sort(key=lambda row: (row.status, row.sku))
    return rows


def _supplier_tradeoff(state: SystemState, supplier_id: str, sku: str) -> str:
    current = state.suppliers[supplier_id]
    peers = [item for item in state.suppliers.values() if item.sku == sku]
    if not peers:
        return "no comparison available"
    fastest = min(peer.lead_time_days for peer in peers)
    cheapest = min(peer.unit_cost for peer in peers)
    if current.lead_time_days == fastest and current.unit_cost > cheapest:
        return "fast but expensive"
    if current.unit_cost == cheapest and current.lead_time_days > fastest:
        return "cheap but slower"
    return "balanced option"


def supplier_rows(state: SystemState, *, sku: str | None = None, status: str | None = None) -> list[SupplierRowView]:
    target_sku = (sku or "").strip().lower()
    target_status = (status or "").strip().lower()
    items: list[SupplierRowView] = []
    for supplier in state.suppliers.values():
        if target_sku and supplier.sku.lower() != target_sku:
            continue
        if target_status and supplier.status.lower() != target_status:
            continue
        items.append(
            SupplierRowView(
                supplier_id=supplier.supplier_id,
                sku=supplier.sku,
                unit_cost=supplier.unit_cost,
                lead_time_days=supplier.lead_time_days,
                reliability=supplier.reliability,
                is_primary=supplier.is_primary,
                status=supplier.status,
                tradeoff=_supplier_tradeoff(state, supplier.supplier_id, supplier.sku),
            )
        )
    items.sort(key=lambda row: (row.sku, -row.reliability, row.lead_time_days))
    return items


def alerts(state: SystemState) -> list[AlertView]:
    items: list[AlertView] = []
    for event in state.active_events:
        level = "critical" if event.severity >= 0.8 else "warning"
        items.append(
            AlertView(
                level=level,
                title=event.type.value.replace("_", " ").title(),
                message=f"Detected from {event.source} with severity {event.severity:.2f}",
                source="event",
                event_type=event.type.value,
                entity_ids=event.entity_ids,
            )
        )
    for row in inventory_rows(state):
        if row.status not in {"low", "out_of_stock"}:
            continue
        items.append(
            AlertView(
                level="critical" if row.status == "out_of_stock" else "warning",
                title=f"{row.sku} inventory {row.status.replace('_', ' ')}",
                message=(
                    f"On hand {row.on_hand}, incoming {row.incoming_qty}, reorder point {row.reorder_point}"
                ),
                source="inventory",
                entity_ids=[row.sku],
            )
        )
        if len(items) >= 6:
            break
    return items[:6]


def pending_approval_view(state: SystemState) -> PendingApprovalView | None:
    if state.pending_plan is None or not state.decision_logs:
        return None
    decision = state.decision_logs[-1]
    return PendingApprovalView(
        decision_id=decision.decision_id,
        approval_status=decision.approval_status.value,
        approval_reason=decision.approval_reason,
        plan=plan_view(state.pending_plan),
    )


def latest_trace_view(state: SystemState) -> TraceView:
    trace = state.latest_trace
    latest_decision = state.decision_logs[-1] if state.decision_logs else None
    latest_event = state.active_events[-1] if state.active_events else None
    if trace is None:
        return TraceView(
            mode=state.mode.value,
            current_branch=state.mode.value,
            event=event_view(latest_event) if latest_event else None,
            latest_plan=plan_view(state.latest_plan),
            decision_id=latest_decision.decision_id if latest_decision else None,
            selected_strategy=state.latest_plan.strategy_label if state.latest_plan else None,
            candidate_count=len(latest_decision.candidate_evaluations) if latest_decision else 0,
            selection_reason=latest_decision.selection_reason if latest_decision else None,
            candidate_evaluations=(
                [candidate_evaluation_view(item) for item in latest_decision.candidate_evaluations]
                if latest_decision
                else []
            ),
            approval_pending=state.pending_plan is not None,
            approval_reason=latest_decision.approval_reason if latest_decision else "",
            critic_summary=latest_decision.critic_summary if latest_decision else None,
        )

    steps = [
        AgentStepView(
            agent=step.node_key,
            node_type=step.node_type,
            status=step.status,
            started_at=step.started_at,
            completed_at=step.completed_at,
            mode_snapshot=step.mode_snapshot,
            summary=step.summary,
            reasoning_source=step.reasoning_source,
            input_snapshot=step.input_snapshot,
            output_snapshot=step.output_snapshot,
            observations=step.observations,
            risks=step.risks,
            downstream_impacts=step.downstream_impacts,
            recommended_action_ids=step.recommended_action_ids,
            tradeoffs=step.tradeoffs,
            llm_used=step.llm_used,
            llm_error=step.llm_error,
        )
        for step in trace.steps
    ]
    return TraceView(
        trace_id=trace.trace_id,
        status=trace.status,
        started_at=trace.started_at,
        completed_at=trace.completed_at,
        mode_before=trace.mode_before,
        mode_after=trace.mode_after,
        mode=state.mode.value,
        current_branch=trace.current_branch,
        terminal_stage=trace.terminal_stage,
        event=event_view(trace.event) if trace.event else event_view(latest_event) if latest_event else None,
        route_decisions=[
            RouteDecisionView(
                from_node=item.from_node,
                outcome=item.outcome,
                to_node=item.to_node,
                reason=item.reason,
            )
            for item in trace.route_decisions
        ],
        steps=steps,
        latest_plan=plan_view(state.latest_plan),
        decision_id=trace.decision_id or latest_decision.decision_id if latest_decision else trace.decision_id,
        selected_strategy=trace.selected_strategy or (state.latest_plan.strategy_label if state.latest_plan else None),
        candidate_count=trace.candidate_count,
        selection_reason=trace.selection_reason or (latest_decision.selection_reason if latest_decision else None),
        candidate_evaluations=(
            [candidate_evaluation_view(item) for item in latest_decision.candidate_evaluations]
            if latest_decision
            else []
        ),
        approval_pending=trace.approval_pending,
        approval_reason=trace.approval_reason,
        execution_status=trace.execution_status,
        critic_summary=trace.critic_summary or (latest_decision.critic_summary if latest_decision else None),
    )


def reflection_views(state: SystemState) -> list[ReflectionView]:
    if state.memory is None:
        return []
    items = [
        ReflectionView(
            note_id=item.note_id,
            run_id=item.run_id,
            scenario_id=item.scenario_id,
            plan_id=item.plan_id,
            mode=item.mode,
            approval_status=item.approval_status,
            summary=item.summary,
            lessons=item.lessons,
            pattern_tags=item.pattern_tags,
            follow_up_checks=item.follow_up_checks,
            llm_used=item.llm_used,
            llm_error=item.llm_error,
        )
        for item in state.memory.reflection_notes
    ]
    return list(reversed(items))


def scenario_outcomes(state: SystemState) -> list[ScenarioOutcomeView]:
    if state.memory is None:
        return []
    items: list[ScenarioOutcomeView] = []
    for scenario_id, payload in sorted(state.memory.scenario_outcomes.items()):
        items.append(
            ScenarioOutcomeView(
                scenario_id=scenario_id,
                runs=int(payload.get("runs", 0)),
                latest_run_id=payload.get("latest_run_id"),
                latest_plan_id=payload.get("latest_plan_id"),
                latest_approval_status=payload.get("latest_approval_status"),
                latest_reflection_status=payload.get("latest_reflection_status"),
                latest_kpis=payload.get("latest_kpis", {}),
                history=payload.get("history", []),
            )
        )
    return items


def control_tower_summary(state: SystemState) -> ControlTowerSummaryResponse:
    if state.kpis.decision_latency_ms < 0.0:
        state.kpis = recompute_kpis(state)
    return ControlTowerSummaryResponse(
        mode=state.mode.value,
        kpis=kpi_view(state.kpis),
        alerts=alerts(state),
        active_events=[event_view(event) for event in state.active_events],
        latest_plan=plan_view(state.latest_plan),
        pending_approval=pending_approval_view(state),
        decision_count=len(state.decision_logs),
        scenario_history_count=len(state.scenario_history),
    )


def control_tower_state(state: SystemState) -> ControlTowerStateResponse:
    return ControlTowerStateResponse(
        summary=control_tower_summary(state),
        inventory=inventory_rows(state),
        suppliers=supplier_rows(state),
        reflections=reflection_views(state),
        latest_trace=latest_trace_view(state),
    )


def find_decision(state: SystemState, decision_id: str) -> DecisionLog:
    for item in reversed(state.decision_logs):
        if item.decision_id == decision_id:
            return item
    raise_not_found("decision", decision_id)


def build_event_from_request(
    *,
    event_type,
    severity: float,
    source: str,
    entity_ids: list[str],
    payload: dict[str, Any],
) -> Event:
    timestamp = utc_now()
    return Event(
        event_id=f"evt_api_{event_type.value}_{int(timestamp.timestamp())}",
        type=event_type,
        source=source,
        severity=severity,
        entity_ids=entity_ids,
        occurred_at=timestamp,
        detected_at=timestamp,
        payload=payload,
        dedupe_key=f"{event_type.value}:{entity_ids}:{payload}",
    )
