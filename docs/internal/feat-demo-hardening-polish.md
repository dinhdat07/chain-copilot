# Feature Plan: Demo Hardening + Polish

## Objective

Increase demo reliability by fixing brittle reset behavior, blocking invalid actions during pending approval, clarifying the current blocked state, and adding focused hardening tests.

## Scope

- Add clean reset behavior for API and Streamlit demo restarts.
- Block daily-plan and scenario execution while approval is pending.
- Improve visibility of the current approval-blocked state in the UI.
- Add focused tests for reset and approval edge cases.

## Files To Modify

- [x] `core/memory.py`
- [x] `orchestrator/service.py`
- [x] `simulation/runner.py`
- [x] `api.py`
- [x] `ui/dashboard.py`
- [x] `ui/overview.py`
- [x] `ui/scenarios.py`
- [x] `ui/decision_log.py`
- [x] `tests/test_demo_flow_api.py`
- [x] `tests/test_scenarios.py`
- [x] `tests/test_demo_hardening.py`

## Implementation Steps

- [x] Add store reset support for decision logs, snapshots, and scenario runs.
- [x] Add a shared pending-approval guard for runtime actions.
- [x] Block daily-plan execution while a decision is pending approval.
- [x] Block scenario execution while a decision is pending approval.
- [x] Add an API reset endpoint for clean demo restarts.
- [x] Update Streamlit reset to clear both session and persisted state.
- [x] Surface blocked-state messaging in Overview and Scenarios.
- [x] Improve Decision Log empty/blocking state clarity.
- [x] Add hardening tests for reset, blocking, and reject behavior.

## Testing Approach

- [x] Run `ruff check api.py core orchestrator simulation ui tests`
- [x] Run `pytest -q tests/test_demo_flow_api.py tests/test_demo_hardening.py tests/test_scenarios.py`
- [x] Run `pytest -q`
