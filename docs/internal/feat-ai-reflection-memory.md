# Feature Plan: AI Reflection Memory

## Objective

Add structured AI reflection notes after actual scenario outcomes while preserving deterministic supplier reliability updates, route-prior updates, and scenario history persistence.

## Scope

- Keep numeric learning rule-based and deterministic.
- Add qualitative reflection notes from actual run outcomes.
- Persist lessons, pattern tags, and follow-up checks in memory snapshots.
- Defer reflection-note creation when a scenario ends with pending approval.
- Finalize deferred reflection when approval is resolved and the outcome becomes real.
- Do not change scenario definitions, scoring, or approval thresholds.

## Files To Modify

- [x] `core/models.py`
- [x] `simulation/learning.py`
- [x] `simulation/runner.py`
- [x] `orchestrator/service.py`
- [x] `llm/service.py`
- [x] `orchestrator/prompts.py`
- [x] `tests/test_ai_reflection_memory.py`
- [x] `tests/test_explainability_learning.py`

## Implementation Steps

- [x] Add structured reflection models:
  - `ReflectionNote`
- [x] Extend `MemorySnapshot` with:
  - `reflection_notes`
  - `pattern_tag_counts`
- [x] Extend `ScenarioRun` with reflection status/metadata so pending approval runs can be finalized later.
- [x] Keep deterministic numeric updates to:
  - supplier reliability
  - route disruption priors
  - scenario outcome history
- [x] Add an LLM reflection prompt and schema based on actual events, selected plan, KPI deltas, and approval outcome.
- [x] Add deterministic fallback reflection generation if LLM is unavailable or returns invalid output.
- [x] Create reflection notes immediately for auto-applied or already-approved runs.
- [x] Defer reflection notes for pending-approval runs.
- [x] Finalize deferred reflection when approval resolves through the existing approval service path.
- [x] Persist updated memory and scenario history to SQLite state snapshots.

## Testing Approach

- [x] Add test that auto-applied scenario runs persist a reflection note.
- [x] Add test that pending-approval runs defer reflection.
- [x] Add test that approving a pending scenario finalizes reflection.
- [x] Add test that repeated runs accumulate reflection notes and pattern tag counts.
- [x] Add test that LLM failure falls back to deterministic reflection notes.
- [x] Run `./.venv/bin/ruff check core llm orchestrator simulation tests`
- [x] Run `./.venv/bin/pytest -q tests/test_ai_reflection_memory.py tests/test_explainability_learning.py`
- [x] Run `./.venv/bin/pytest -q`
