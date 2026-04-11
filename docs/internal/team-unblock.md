# Team Unblock

## Frontend Can Mock Against Now

- `RunRecord`
- `EventEnvelope`
- `TraceStep` with timing and fallback fields
- `ExecutionRecord`
- `ErrorResponse`
- API contracts:
  - `POST /api/v1/events/ingest`
  - `GET /api/v1/runs/{run_id}`
  - `GET /api/v1/runs/{run_id}/trace`
  - `GET /api/v1/execution/{execution_id}`

## Stable Backend Modules

- `core/runtime_records.py`
- `core/memory.py` new runtime persistence methods
- `app_api/schemas.py` runtime API contracts
- `app_api/routers.py` new foundation endpoints

## Still Provisional

- replay APIs beyond trace lookup
- event listing/query APIs
- constraint and feasibility outputs
- memory retrieval influence payloads
- real execution dispatch adapters
