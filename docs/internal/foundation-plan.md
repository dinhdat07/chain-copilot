# Foundation Plan

## Dependency Order

1. Lock shared contracts:
   - RunRecord
   - EventEnvelope
   - TraceStep extensions
   - ExecutionRecord
   - minimum error contract
2. Add persistence for:
   - run ledger
   - event log
   - traces
   - execution records
3. Refactor runtime lifecycle:
   - unique run id per orchestration
   - run metadata persisted after each orchestration/approval cycle
4. Expose team-unblocking APIs:
   - `POST /api/v1/events/ingest`
   - `GET /api/v1/runs/{run_id}`
   - `GET /api/v1/runs/{run_id}/trace`
   - `GET /api/v1/execution/{execution_id}`

## Implementing Now

- Stable typed runtime records and schemas
- SQLite-backed persistence for the new records
- Unique `run_id` generation for daily plan, event response, scenario steps, and approval resolution
- Historical trace lookup by run
- Simulation-backed execution records
- Minimum observability:
  - run duration
  - step duration
  - fallback flags

## Deferred

- Full `GET /runs` listing and richer history filters
- Replay engine beyond historical lookup
- Constraint engine and feasibility outputs
- Memory retrieval injection
- Real external execution adapters
- Async event queue / broker
- Advanced feature-flag and retry subsystems

## Why

This slice is the minimum backbone that:

- gives frontend and other contributors stable contracts
- separates live runtime state from persisted historical artifacts
- preserves the current demo flow
- avoids premature infrastructure and integration work
