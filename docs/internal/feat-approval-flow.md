# Feature Plan: Approval Flow

## Objective

Make the approval workflow explicit and UI-ready by exposing richer pending approval details, typed approval command results, and consistent approval state propagation across summary, plan, and trace views.

## Scope

- [x] Add a richer pending approval read model with allowed actions and plan/decision context
- [x] Add a typed approval command response for approve, reject, and safer-plan actions
- [x] Propagate approval status consistently into summary, latest plan, pending approval, and trace views
- [x] Update trace state after approval actions so the latest workflow outcome is visible
- [x] Add tests for pending, approved, rejected, and safer-plan transitions

## Files To Modify

- [ ] `core/models.py`
- [x] `orchestrator/service.py`
- [x] `app_api/schemas.py`
- [x] `app_api/services.py`
- [x] `app_api/routers.py`
- [x] `tests/test_backend_api_alignment.py`
- [ ] `tests/test_demo_flow_api.py`

## Implementation Steps

- [x] Add approval metadata to plan and pending approval DTOs
- [x] Add a dedicated approval detail/result schema
- [x] Expose `GET /api/v1/approvals/{decision_id}` for a specific approval item
- [x] Return a typed result from `POST /api/v1/approvals/{decision_id}`
- [x] Update approval actions to keep latest trace synchronized:
  - [x] approve
  - [x] reject
  - [x] safer_plan
- [x] Ensure summary/latest plan reflect approval status after each action
- [x] Add tests covering:
  - [x] pending approval detail
  - [x] approve transition
  - [x] reject transition
  - [x] safer plan transition

## Testing Approach

- [x] Run targeted pytest coverage for approval-flow contracts
- [x] Run existing demo/API tests to confirm compatibility
- [x] Manually verify pending approval, approve, reject, and safer-plan responses via FastAPI
