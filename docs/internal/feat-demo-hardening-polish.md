# Feature Plan: Demo Hardening + Polish

## Objective

Increase demo reliability by fixing brittle reset behavior, blocking invalid actions during pending approval, and polishing the guided demo flow so judges can clearly follow normal mode, disruption, replanning, approval, and updated state.

## Scope

- Add clean reset behavior for API and Streamlit demo restarts.
- Block daily-plan and scenario execution while approval is pending.
- Improve visibility of the current approval-blocked state in the UI.
- Add guided demo-flow presentation for mode, selected plan, and state progression.
- Add focused tests for reset, approval edge cases, and demo presentation helpers.

## Files To Modify

- [x] `core/memory.py`
- [x] `orchestrator/service.py`
- [x] `simulation/runner.py`
- [x] `api.py`
- [x] `ui/dashboard.py`
- [x] `ui/overview.py`
- [x] `ui/scenarios.py`
- [x] `ui/decision_log.py`
- [x] `ui/components.py`
- [x] `docs/demo_script.md`
- [x] `tests/test_demo_flow_api.py`
- [x] `tests/test_scenarios.py`
- [x] `tests/test_demo_hardening.py`
- [x] `tests/test_demo_presenter.py`

## Implementation Steps

- [x] Add store reset support for decision logs, snapshots, and scenario runs.
- [x] Add a shared pending-approval guard for runtime actions.
- [x] Block daily-plan execution while a decision is pending approval.
- [x] Block scenario execution while a decision is pending approval.
- [x] Add an API reset endpoint for clean demo restarts.
- [x] Update Streamlit reset to clear both session and persisted state.
- [x] Surface blocked-state messaging in Overview and Scenarios.
- [x] Improve Decision Log empty/blocking state clarity.
- [x] Add a guided control-tower status section for mode, selected plan, and demo progress.
- [x] Improve scenario descriptions and latest-event presentation for judges.
- [x] Replace raw JSON plan/KPI dumps with friendlier plan and KPI views.
- [x] Replace deprecated Streamlit width usage and raw persisted-log table with a friendlier detail flow.
- [x] Update the demo script to match the polished flow.
- [x] Add hardening tests for reset, blocking, and reject behavior.
- [x] Add helper tests for demo-flow presentation logic.

## Testing Approach

- [x] Run `ruff check api.py core orchestrator simulation ui tests`
- [x] Run `pytest -q tests/test_demo_flow_api.py tests/test_demo_hardening.py tests/test_scenarios.py`
- [x] Run `pytest -q`
