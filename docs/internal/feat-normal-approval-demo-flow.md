# Feature Plan: Normal + Approval Demo Flow

## Objective

Make the judged demo path explicit in the product by adding a normal daily planning flow, visible before/after KPI comparison, pending approval controls, and minimal API wiring that reuses the existing LangGraph orchestration and deterministic planner.

## Scope

- Add a daily plan execution path for normal mode.
- Surface before/after baseline for the latest daily or scenario-driven plan.
- Show pending approval details in the dashboard.
- Add approve, reject, and request-safer-plan actions.
- Wire matching API endpoints for demo and test coverage.
- Update the demo script to match the new flow.

## Files To Modify

- [x] `api.py`
- [x] `orchestrator/service.py`
- [x] `ui/dashboard.py`
- [x] `ui/overview.py`
- [x] `ui/scenarios.py`
- [x] `ui/decision_log.py`
- [x] `ui/components.py`
- [x] `docs/demo_script.md`
- [x] `tests/test_demo_flow_api.py`

## Implementation Steps

- [x] Add a shared service layer for daily-plan execution and approval actions.
- [x] Implement a deterministic daily-plan path that runs through the LangGraph graph without introducing a new planner path.
- [x] Add API endpoint for daily plan execution.
- [x] Add API endpoint for safer-plan request using stricter guardrails on the current pending plan.
- [x] Update approval endpoint to reuse the shared service layer.
- [x] Add overview UI action to run daily plan.
- [x] Render baseline vs projected KPI comparison for the latest decision.
- [x] Render pending approval panel with approve, reject, and safer-plan controls.
- [x] Surface approval state more clearly in scenario and decision-log views.
- [x] Update the demo script to match the reviewed flow.

## Testing Approach

- [x] Add API tests for daily-plan execution.
- [x] Add API tests for approve and reject flows.
- [x] Add API tests for safer-plan flow on an approval-required scenario.
- [x] Run `ruff check api.py orchestrator ui tests`.
- [x] Run `pytest -q`.
