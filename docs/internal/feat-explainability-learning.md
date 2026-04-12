# Feature Plan: Explainability + Learn Phase

## Objective

Close the remaining gap in the MVP loop by adding grounded, deterministic decision explanations and simple deterministic learning updates after scenario runs.

## Scope

- Derive explanations from real `score_breakdown`, KPI deltas, selected actions, and rejected alternatives.
- Log whether approval was required and why.
- Persist scenario outcomes into memory after each run.
- Update supplier reliability and route disruption priors with simple rule-based heuristics.
- Preserve repeated-run history for the same scenario.
- Add tests for explanation completeness and memory persistence.

## Files To Modify

- [x] `core/models.py`
- [x] `policies/explainability.py`
- [x] `agents/planner.py`
- [x] `simulation/runner.py`
- [x] `core/memory.py`
- [x] `ui/components.py`
- [x] `ui/decision_log.py`
- [x] `tests/test_explainability_learning.py`

## Implementation Steps

- [x] Extend `DecisionLog` and `ScenarioRun` with fields needed for grounded explanations and repeated-run traceability.
- [x] Add deterministic explainability helpers for score breakdown, KPI deltas, selected-action wins, and rejection reasons.
- [x] Update the planner to write explanation and approval metadata into the decision log.
- [x] Add deterministic learning updates to scenario execution for supplier reliability and route disruption priors.
- [x] Persist repeated scenario runs without overwriting previous runs.
- [x] Surface the new explanation fields in the existing decision-log UI without redesigning the app.
- [x] Add focused tests for explanation completeness, memory persistence, and repeated scenario updates.

## Testing Approach

- [x] Run `pytest -q tests/test_explainability_learning.py`
- [x] Run `pytest -q`
- [x] Run `ruff check agents core policies simulation ui tests`
