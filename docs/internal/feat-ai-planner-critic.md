# Feature Plan: AI Planner + Critic

## Objective

Move plan generation into an AI-centered planner and critic loop while keeping deterministic plan simulation, score computation, approval gating, and execution guards authoritative.

## Scope

- Generate exactly three candidate plan strategies:
  - `cost_first`
  - `balanced`
  - `resilience_first`
- Planner may only reference known action ids produced by existing specialist agents.
- Add an optional critic review stage after candidate evaluation and final deterministic selection.
- Preserve `latest_plan`, `pending_plan`, approval endpoints, and current UI flow compatibility.
- Keep deterministic fallback when planner or critic output is unavailable or invalid.

## Files To Modify

- [x] `core/models.py`
- [x] `agents/planner.py`
- [x] `agents/critic.py`
- [x] `orchestrator/graph.py`
- [x] `orchestrator/router.py`
- [x] `llm/service.py`
- [x] `orchestrator/prompts.py`
- [x] `tests/test_ai_planner_critic.py`

No direct code changes were required in `tests/test_llm_planner_explanations.py` or `tests/test_langgraph_paths.py`; compatibility was verified by running them unchanged.

## Implementation Steps

- [x] Add structured candidate-plan and critic-review models:
  - `CandidatePlanDraft`
  - `CandidatePlanEvaluation`
- [x] Extend `Plan` with optional strategy metadata and critic summary.
- [x] Extend `DecisionLog` with candidate evaluations, deterministic selection reason, planner fallback diagnostics, and critic metadata.
- [x] Add planner prompt and JSON schema for exactly three strategies referencing known action ids only.
- [x] Add deterministic fallback candidate-plan generation for the same three strategies.
- [x] Simulate and score each candidate deterministically.
- [x] Run deterministic approval guardrails on each candidate.
- [x] Select the final plan deterministically using score and fixed tie-breaks.
- [x] Add a critic prompt and review schema for candidate-plan blind spots and cautions.
- [x] Add a LangGraph critic node after planner.
- [x] Preserve approval and execution routing after critic.
- [x] Keep the existing plan/explanation enrichment path compatible with the new selected plan.

## Testing Approach

- [x] Add test that normal mode produces three candidate evaluations and one selected plan.
- [x] Add test that crisis mode can select the resilience-first plan.
- [x] Add test that approval routing still works for a high-risk selected plan through the unchanged LangGraph path tests.
- [x] Add test that invalid planner output falls back to deterministic candidate generation.
- [x] Add test that critic failure does not break planning or execution.
- [x] Run `./.venv/bin/ruff check agents core llm orchestrator tests`
- [x] Run `./.venv/bin/pytest -q tests/test_ai_planner_critic.py tests/test_langgraph_paths.py tests/test_llm_planner_explanations.py`
- [x] Run `./.venv/bin/pytest -q`
