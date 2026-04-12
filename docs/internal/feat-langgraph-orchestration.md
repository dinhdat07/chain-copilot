# Feature Plan: LangGraph Orchestration

## Objective

Replace the custom orchestrator with a real LangGraph-based state graph while preserving the current `build_graph().invoke(state, event)` contract used by the API, simulation runner, and UI.

## Scope

- Real LangGraph state graph and node wiring
- Nodes for risk, demand, inventory, supplier, logistics, planner, approval, and execution
- Routing for normal, crisis, and approval-required paths
- Minimal adapter layer to preserve current callers
- Integration tests for normal, crisis, and approval paths

## Files to Modify

- [x] `orchestrator/graph.py`
- [x] `orchestrator/router.py`
- [ ] `simulation/runner.py` (no change needed; adapter contract preserved)
- [x] `tests/test_scenarios.py`
- [x] `tests/test_langgraph_paths.py`

## Implementation Steps

- [x] Define a LangGraph wrapper state around `SystemState` and `Event`
- [x] Implement risk, demand, inventory, supplier, logistics, planner, approval, and execution nodes
- [x] Add conditional routing for normal / crisis after risk
- [x] Add conditional routing for approval-required path after planner
- [x] Preserve the current adapter contract with `build_graph().invoke(state, event)`
- [x] Update scenario runner only if adapter usage changes
- [x] Add tests for normal path
- [x] Add tests for crisis path
- [x] Add tests for approval path

## Testing Approach

- Run targeted pytest coverage for new graph path tests and existing scenario tests
- Verify that daily normal invocation with `event=None` yields an applied plan
- Verify that a disruption scenario still produces crisis or approval behavior
- Verify that a high-risk scenario leaves a pending approval plan instead of auto-applying
