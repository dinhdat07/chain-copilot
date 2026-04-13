# Merge And Integration Strategy

## Branch Inventory

### `feat/chaincopilot-mvp`

- Current baseline branch and current `feat/merge-and-integration` `HEAD`
- Old MVP backend only
- Contains legacy FastAPI app in `api.py`
- Does not include the `app_api/` service layer in the checked-out source tree
- Does not include run ledger, trace replay, or service observability source files

### `feat/service-observability-reliability`

- Real implementation of Task Group A, B, and G foundation work
- Adds the control tower service layer:
  - `app_api/__init__.py`
  - `app_api/routers.py`
  - `app_api/schemas.py`
  - `app_api/services.py`
- Adds run and trace persistence:
  - `core/runtime_records.py`
  - `core/runtime_tracking.py`
- Adds orchestration service integration:
  - `orchestrator/service.py`
- Adds policy hooks and explainability support:
  - `policies/constraints.py`
  - `policies/explainability.py`
- Adds service-level tests for:
  - foundation run ledger
  - run history replay
  - approval flow
  - agent trace
  - service observability and reliability
- Provides the stable backend contract closest to the current UI hook:
  - `/api/v1/control-tower/summary`
  - `/api/v1/trace/latest`
  - `/api/v1/runs`
  - `/api/v1/runs/{run_id}`
  - `/api/v1/runs/{run_id}/trace`
  - `/api/v1/runs/{run_id}/state`
  - `/api/v1/execution/{execution_id}`
  - `/api/v1/decision-logs/{decision_id}`
  - `/api/v1/approvals/{decision_id}`
  - `/api/v1/approvals/pending`
  - `/api/v1/plan/daily`
  - `/api/v1/scenarios/run`
  - `/api/v1/what-if`

### `feat/api-execution-dispatch`

- Builds on top of the service-observability stack
- Includes the `feat/service-observability-reliability` history and the policy hooks history
- Adds Task Group E1 execution lifecycle and dispatch implementation:
  - `execution/dispatch_service.py`
  - `execution/state_machine.py`
  - `execution/models.py`
  - `execution/adapters/base.py`
  - `execution/adapters/stubs.py`
- Extends service layer for execution-oriented APIs:
  - `/api/v1/execution`
  - `/api/v1/execution/{plan_id}/dispatch`
  - `/api/v1/execution/{execution_id}/progress`
  - `/api/v1/execution/{execution_id}/complete`
- Also modifies planner, runtime records, state, policies, and service views to surface execution lifecycle data
- Contains unwanted artifacts that must not be merged as-is:
  - `node_modules/`
  - `package-lock.json`
  - `package.json`
  - `yarn.lock`
  - `.streamlit/config.toml`
  - additional Streamlit/UI-only files unrelated to backend integration

### `origin/forecast-demand`

- Based on the service-observability stack, not on raw MVP
- Does not add a separate service framework
- Changes a focused set of files related to forecasting and demand realism:
  - `app_api/schemas.py`
  - `app_api/services.py`
  - `core/models.py`
  - `core/state.py`
  - `agents/supplier.py`
  - `actions/switch_supplier.py`
  - `policies/constraints.py`
  - `simulation/learning.py`
  - `data/inventory.csv`
  - `data/suppliers.csv`
- Main effects:
  - richer SKU and supplier mock data
  - inventory schema/data changes
  - demand and replenishment-related state/service adjustments
  - learning updates tied to supplier reliability
- This branch should not be merged wholesale after execution-dispatch without review because it touches overlapping service, state, and policy files

## Recommended Base Branch

Use `feat/api-execution-dispatch` as the integration base.

Reasoning:

- It already includes the A/B/G foundation from `feat/service-observability-reliability`
- It already includes the E1 execution lifecycle work the UI will need next
- It is the closest backend branch to the control tower product shape:
  - event ingestion
  - run ledger
  - decision log access
  - replay trace
  - execution lifecycle
- It reduces rework because execution support is harder to layer in later than forecast data refinements

Important caveat:

- Do not merge `feat/api-execution-dispatch` blindly into the target branch
- Port backend-only changes and exclude vendor and UI/package artifacts

## Merge Order

1. Create or reset `feat/merge-and-integration` from `feat/api-execution-dispatch`

- This makes the base branch immediately include A/B/G + E1
- It avoids replaying several historical merges manually

2. Remove accidental non-backend artifacts from the integrated branch

- Delete:
  - `node_modules/`
  - `package-lock.json`
  - `package.json`
  - `yarn.lock`
- Keep `.streamlit/config.toml` only if the Streamlit fallback demo still needs it

3. Validate the service contract against the current UI client

- Confirm these endpoints remain stable:
  - `/api/v1/control-tower/summary`
  - `/api/v1/trace/latest`
  - `/api/v1/runs`
  - `/api/v1/runs/{run_id}`
  - `/api/v1/runs/{run_id}/trace`
  - `/api/v1/runs/{run_id}/state`
  - `/api/v1/execution/{execution_id}`
  - `/api/v1/decision-logs/{decision_id}`
  - `/api/v1/approvals/pending`
  - `/api/v1/approvals/{decision_id}`
  - `/api/v1/plan/daily`
  - `/api/v1/scenarios/run`
  - `/api/v1/what-if`

4. Port forecasting changes selectively from `origin/forecast-demand`

- Cherry-pick or file-port only the backend forecasting and data realism work
- Start with:
  - `core/state.py`
  - `core/models.py`
  - `simulation/learning.py`
  - `agents/supplier.py`
  - `actions/switch_supplier.py`
  - `data/inventory.csv`
  - `data/suppliers.csv`
- Merge `app_api/services.py`, `app_api/schemas.py`, and `policies/constraints.py` manually, not wholesale

5. Reconcile API payloads after forecast data integration

- Ensure run, state, plan, approval, and execution views still match the UI-presenter expectations
- Preserve run history and execution contracts from the execution branch

6. Run the backend and current UI client together for end-to-end verification

- Focus on:
  - past runs
  - run details
  - replay trace
  - before/after run state
  - approval detail
  - execution detail

## Conflict Resolution Strategy

### Source-of-truth priority

When conflicts occur, resolve in this order:

1. `feat/api-execution-dispatch` for:
  - runtime records
  - execution lifecycle
  - dispatch service
  - execution-related API schema
2. `feat/service-observability-reliability` for:
  - run ledger contract stability
  - trace and replay structure
  - service observability
3. `origin/forecast-demand` for:
  - inventory and supplier mock data realism
  - replenishment inputs
  - learning improvements tied to the richer dataset

### File-specific rules

- `app_api/services.py`
  - keep run/event/execution flow from execution-dispatch
  - manually fold in forecast-demand data shaping and learning updates
- `app_api/schemas.py`
  - preserve execution and run response shapes already used by UI
  - add only forecast-related fields that are additive and non-breaking
- `core/state.py`
  - accept forecast-demand data-loading and KPI/reorder improvements
  - preserve runtime/run-id compatibility from the service stack
- `policies/constraints.py`
  - preserve policy hooks already used in the planner
  - merge only additive forecast/data logic
- `data/*.csv`
  - prefer forecast-demand versions for realism if schema stays compatible

### Safety rules

- Never reintroduce the old MVP-only `api.py` as the primary contract
- Do not duplicate service logic across `api.py` and `app_api/*`
- Keep legacy endpoints only as compatibility shims if still needed by demos

## UI Alignment Requirements

Current UI client on `supply-chain-management/scm-demo` expects these backend capabilities:

- control tower summary
- latest trace
- run history
- run detail
- run trace
- run state replay
- decision detail by `decision_id`
- pending approval detail
- approval submit
- execution detail by `execution_id`
- daily plan trigger
- scenario run
- what-if preview

Required backend adjustments after merge:

1. Keep the service-layer endpoints above as the canonical contract
2. Ensure `decision_id` persists for historical runs so `/decision-logs/{decision_id}` works for old run rows
3. Ensure `execution_id` is stored on `RunRecord` whenever execution exists
4. Ensure `/runs/{run_id}/state` returns a historical snapshot, not only current live state
5. Ensure `/trace/latest` and `/runs/{run_id}/trace` use the same step schema so the UI can reuse one presenter
6. Keep approval responses rich enough for cards:
  - selected plan summary
  - selected actions
  - before/after KPIs
  - approval reason
  - candidate count
7. Treat `/api/v1/execution`, `/dispatch`, `/progress`, and `/complete` as secondary APIs
  - useful for execution console work
  - not the first blocker for the current UI hook

## Final Integrated Architecture

The integrated backend should resolve to this flow:

1. UI issues a command:
  - daily planning
  - scenario run
  - approval action

2. Control tower service layer receives the request through `app_api/routers.py`

3. Runtime service in `app_api/services.py`:
  - creates or updates an event envelope
  - creates a unique run record
  - executes orchestration against the digital twin state
  - persists trace
  - persists state snapshot
  - persists decision log
  - persists execution record if actions are dispatchable

4. Deterministic policy and constraint code:
  - filters infeasible plans
  - scores candidates
  - sets approval requirements
  - keeps final action safety out of the LLM layer

5. Execution lifecycle layer:
  - creates execution records
  - supports dispatch progression and status transitions

6. Query endpoints expose:
  - current summary
  - latest trace
  - historical runs
  - run-level trace and state replay
  - approval details
  - decision details
  - execution detail

## Remaining Gaps After Integration

### Must fix soon

- Normalize the branch name mismatch in team communication:
  - requested `feat/service-observability`
  - actual branch is `feat/service-observability-reliability`
- Remove accidental backend/UI coupling artifacts from the execution branch
- Verify old decision logs can still be resolved after replay and reload
- Reconcile any schema drift introduced by richer inventory and supplier data

### Partially implemented

- Execution lifecycle exists, but UI usage is still partial
- Forecasting/data realism exists, but it is not yet cleanly merged into the execution-capable backend
- Legacy endpoints and new service endpoints coexist; they should be rationalized after integration stabilizes

### Still missing or future work

- Full async event bus beyond in-process persistence
- richer execution receipts and real adapters
- stronger forecast models beyond current demand/data improvements
- end-to-end integration tests spanning UI contract plus execution transitions
