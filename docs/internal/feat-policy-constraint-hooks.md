# Policy Constraint Hooks

## Objective

Add a thin deterministic policy hook layer so candidate plans expose feasibility, violations, and mode rationale without rewriting the planner or optimizer.

## Scope

- [x] Add constraint violation and mode rationale models to planner outputs
- [x] Evaluate candidate plan feasibility before scoring and final selection
- [x] Expose feasibility and violation details through API responses
- [x] Preserve a safe deterministic fallback when all generated candidates are infeasible
- [x] Run focused regression coverage for planner, API, replay, and execution flows

## Files To Modify

- [x] `docs/internal/feat-policy-constraint-hooks.md`
- [x] `agents/planner.py`
- [x] `app_api/schemas.py`
- [x] `app_api/services.py`
- [x] `core/models.py`
- [x] `policies/constraints.py`
- [x] `tests/test_policy_constraint_hooks.py`

## Implementation Steps

- [x] Introduce `ConstraintViolation` and thread feasibility fields through plan and decision models
- [x] Add deterministic constraint evaluation helpers for blocked routes, delayed suppliers, invalid reorder, and rebalance edge cases
- [x] Add mode rationale output alongside candidate evaluation details
- [x] Filter planner selection toward feasible candidates first
- [x] Synthesize a safe hold-position plan when every generated candidate fails hard constraints
- [x] Verify lint and targeted regression tests

## Testing Approach

- [x] Constraint violations are surfaced for blocked route and capacity overflow cases
- [x] Planner excludes infeasible candidates and falls back to a feasible safe-hold plan
- [x] API responses include feasibility, violations, and mode rationale
- [x] Existing execution, run history, and demo API flows remain green
