# Run History Replay

## Objective

Close the remaining read-only Task A gap by exposing historical run listing and state snapshot lookup for replay and audit analysis.

## Scope

- [x] Add `GET /api/v1/runs`
- [x] Add `GET /api/v1/runs/{run_id}/state`
- [x] Add store helpers for run listing and state snapshot retrieval
- [x] Add typed API response models for run history and historical state
- [x] Add tests for run ordering and state replay lookup

## Files To Modify

- [x] `docs/internal/feat-run-history-replay.md`
- [x] `core/memory.py`
- [x] `app_api/schemas.py`
- [x] `app_api/services.py`
- [x] `app_api/routers.py`
- [x] `tests/test_run_history_replay.py`

## Implementation Steps

- [x] Persisted state snapshots stay unchanged; expose read APIs on top
- [x] List run records sorted by `started_at` descending
- [x] Load state snapshot by run id and render it through existing control-tower state views
- [x] Return 404 for missing run/state artifacts
- [x] Keep endpoints read-only and replay-oriented

## Testing Approach

- [x] Create at least two runs and confirm `GET /runs` ordering
- [x] Fetch historical state by run id and verify it differs across runs
- [x] Verify missing run ids return 404
