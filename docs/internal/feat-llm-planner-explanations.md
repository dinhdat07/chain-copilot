# Feature Plan: LLM Planner + Explanations

## Objective

Add a thin optional Gemini-backed LLM layer for planner narrative, operator explanation, and approval summary while keeping deterministic planning, scoring, approval, and learning logic unchanged.

## Scope

- Add opt-in LLM configuration and Gemini client adapter.
- Generate LLM planner narrative after deterministic planning is complete.
- Generate LLM operator explanation and approval summary from actual plan and score data.
- Persist LLM outputs in separate model fields with deterministic fallback.
- Surface LLM output in the existing Overview and Decision Log UI.
- Add tests for disabled mode, success path, approval path, and failure fallback.

## Files To Modify

- [x] `core/models.py`
- [x] `agents/planner.py`
- [x] `orchestrator/service.py`
- [x] `orchestrator/prompts.py`
- [x] `ui/overview.py`
- [x] `ui/decision_log.py`
- [x] `llm/config.py`
- [x] `llm/gemini_client.py`
- [x] `llm/service.py`
- [x] `tests/test_llm_planner_explanations.py`

## Implementation Steps

- [x] Add LLM config loader with opt-in env vars and deterministic disabled default.
- [x] Add Gemini client using the official `generateContent` REST shape with standard-library HTTP.
- [x] Add a single enrichment service that builds planner narrative, operator explanation, and approval summary from deterministic context only.
- [x] Extend plan and decision-log models with separate LLM fields and metadata.
- [x] Enrich planner-generated decisions without changing deterministic selection or scoring.
- [x] Enrich safer-plan decisions through the existing orchestrator service path.
- [x] Surface optional LLM explanations in Overview and Decision Log with deterministic fallback messaging.
- [x] Add tests for disabled config, successful enrichment, approval summary generation, safer-plan enrichment, and client failure fallback.

## Testing Approach

- [x] Run `ruff check agents core llm orchestrator ui tests`
- [x] Run `pytest -q tests/test_llm_planner_explanations.py`
- [x] Run `pytest -q`
