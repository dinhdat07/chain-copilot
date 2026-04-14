# Feature Plan: Agent Trace

## Objective

Persist a real orchestration trace for each LangGraph run so the backend can expose agent order, branch decisions, planner selection, approval routing, and execution outcome to the external UI.

## Scope

- [x] Add a persisted orchestration trace model to shared state
- [x] Capture node-level execution details directly inside the LangGraph lifecycle
- [x] Record routing decisions for normal, crisis, approval, and execution branches
- [x] Expose the richer trace through `GET /api/v1/trace/latest`
- [x] Add tests for normal flow, crisis flow, and approval-required flow

## Files To Modify

- [x] `core/models.py`
- [ ] `core/state.py`
- [x] `orchestrator/graph.py`
- [x] `app_api/schemas.py`
- [x] `app_api/services.py`
- [x] `tests/test_backend_api_alignment.py`

## Implementation Steps

- [x] Add trace models for orchestration cycle, step records, and route decisions
- [x] Add `latest_trace` to `SystemState`
- [x] Initialize a fresh trace at the start of each graph invocation
- [x] Record step start/completion for risk, demand, inventory, supplier, logistics, planner, critic, approval, and execution
- [x] Capture selected branch after risk and after critic
- [x] Capture planner decision metadata:
  - [x] selected strategy
  - [x] selected plan id
  - [x] candidate count
  - [x] approval-required flag
- [x] Capture execution or approval outcome at the end of the cycle
- [x] Update trace API view to use persisted trace data instead of inferring from `agent_outputs` alone
- [x] Add tests for:
  - [x] normal daily plan trace
  - [x] crisis scenario trace
  - [x] pending approval trace

## Testing Approach

- [x] Run targeted pytest coverage for backend trace contracts
- [x] Run existing LangGraph path tests to confirm orchestration behavior is unchanged
- [x] Manually verify `/api/v1/trace/latest` after a daily plan and after a disruption scenario
