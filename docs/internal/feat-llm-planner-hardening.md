# Feature Plan: LLM Planner Hardening

## Objective

Reduce planner fallback frequency by making candidate-plan prompting and parsing more robust, while keeping deterministic scoring, approval thresholds, and execution guards unchanged.

## Scope

- Harden only the planner path.
- Improve structured prompt guidance for candidate plans.
- Tolerate common strategy-label and action-reference variations from the LLM.
- Repair partial planner output where possible before full fallback.
- Preserve deterministic fallback when output is still unusable.

## Files To Modify

- [x] `docs/internal/feat-llm-planner-hardening.md`
- [x] `llm/service.py`
- [x] `orchestrator/prompts.py`
- [x] `agents/planner.py`
- [x] `tests/test_llm_planner_hardening.py`

No direct code changes were required in `tests/test_ai_planner_critic.py`; compatibility was verified by running it unchanged.

## Implementation Steps

- [x] Strengthen the planner prompt with stricter output guidance and an explicit strategy/action-id contract.
- [x] Add tolerant strategy-label normalization for variants such as:
  - `cost first`
  - `balanced plan`
  - `resilience first`
  - `plan a / b / c`
- [x] Add tolerant action-reference normalization using deterministic aliases derived from candidate actions.
- [x] Accept planner items that reference:
  - `action_ids`
  - `recommended_action_ids`
  - action objects containing `action_id`
- [x] Repair partial planner output by:
  - keeping valid candidate plans
  - filling only missing strategies from deterministic fallback
  - avoiding full fallback when partial recovery is possible
- [x] Improve planner diagnostics so the UI/logs can distinguish:
  - full LLM planner
  - repaired hybrid planner
  - full fallback
- [x] Keep deterministic scoring, tie-breaks, approval gating, and final selection unchanged.

## Testing Approach

- [x] Add tests for strategy-label alias normalization.
- [x] Add tests for action-id alias normalization.
- [x] Add tests for partial candidate-plan recovery without full fallback.
- [x] Verify irreparable planner output still uses deterministic fallback via the existing planner-critic coverage.
- [x] Run `./.venv/bin/ruff check agents llm orchestrator tests`
- [x] Run `./.venv/bin/pytest -q tests/test_llm_planner_hardening.py tests/test_ai_planner_critic.py`
- [x] Run `./.venv/bin/pytest -q`
