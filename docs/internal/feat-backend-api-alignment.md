# Feature Plan: Backend API Alignment

## Objective

Introduce a Control Tower app layer on top of the existing FastAPI backend so the external UI can consume stable, typed, screen-oriented contracts without coupling to raw internal state.

## Scope

- [x] Add typed API schemas for control tower summary, inventory, suppliers, plans, approvals, trace, decision logs, and reflections
- [x] Add an application runtime/service layer that owns state, graph, runner, and persistence access
- [x] Add query helpers that translate `SystemState` into UI-facing response models
- [x] Add router structure under an app-layer package and keep existing routes compatible where practical
- [x] Add a unified approval command endpoint while preserving current approval behavior
- [x] Add API contract tests for read endpoints and approval state transitions

## Files To Modify

- [x] `api.py`
- [ ] `orchestrator/service.py`
- [ ] `core/models.py`
- [x] `tests/test_demo_flow_api.py`

## Files To Add

- [ ] `app_runtime.py`
- [x] `app_api/schemas.py`
- [x] `app_api/services.py`
- [x] `app_api/routers.py`
- [x] `tests/test_backend_api_alignment.py`

## Implementation Steps

- [x] Create a runtime wrapper for store, state, graph, and scenario runner
- [x] Create Pydantic response models for dashboard/state/read endpoints
- [x] Add query functions to build summaries, alerts, event feed, inventory rows, supplier rows, plan detail, approval detail, decision detail, trace, and reflection history
- [x] Refactor FastAPI route handlers to use the runtime/service layer
- [x] Add new endpoints:
  - [x] `GET /api/v1/control-tower/summary`
  - [x] `GET /api/v1/control-tower/state`
  - [x] `GET /api/v1/inventory`
  - [x] `GET /api/v1/suppliers`
  - [x] `GET /api/v1/events`
  - [x] `GET /api/v1/plans/latest`
  - [x] `GET /api/v1/approvals/pending`
  - [x] `GET /api/v1/decision-logs/{decision_id}`
  - [x] `GET /api/v1/trace/latest`
  - [x] `GET /api/v1/reflections`
  - [x] `POST /api/v1/approvals/{decision_id}`
- [x] Preserve existing command endpoints used by current tests and demo flows
- [x] Add tests for new contracts and state transitions

## Testing Approach

- [x] Run targeted pytest coverage for the new API contract tests
- [x] Run existing demo/API tests to confirm backward compatibility
- [x] Manually verify `GET /api/v1/control-tower/summary` and approval flow responses with TestClient
