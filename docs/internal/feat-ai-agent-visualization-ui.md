# Feature Plan: AI Agent Visualization UI

## Objective

Make the system's AI coordination visible in the dashboard so judges can immediately understand how agents collaborate, how plans are chosen, and how the workflow moves from normal to crisis, approval, execution, and learning.

## Scope

- Add a dedicated visualization page for AI agent transparency.
- Render a node-based pipeline view showing agent flow and branching.
- Add a per-node reasoning panel driven by existing state and decision-log data.
- Surface candidate plans, selected strategy, critic output, and reflection memory.
- Reuse existing backend data; avoid new orchestration logic.

## Files To Modify

- [x] `docs/internal/feat-ai-agent-visualization-ui.md`
- [x] `ui/dashboard.py`
- [x] `ui/components.py`
- [x] `ui/agent_visualization.py`
- [x] `tests/test_agent_visualization_ui.py`

No direct code changes were required in `tests/test_demo_presenter.py`; compatibility was verified by running it unchanged.

## Implementation Steps

- [x] Add an `AI Agents` page to the dashboard navigation.
- [x] Build a Graphviz-based pipeline view with nodes for:
  - Risk
  - Demand
  - Inventory
  - Supplier
  - Logistics
  - Planner
  - Critic
  - Decision Engine
  - Approval Gate
  - Execution
  - Reflection / Memory
- [x] Color and highlight nodes by mode and execution status:
  - normal
  - crisis
  - approval pending
  - executed
  - learning complete
- [x] Add a node selector and per-node reasoning panel showing:
  - input state summary
  - output summary
  - recommended actions / key factors
  - deterministic or AI reasoning availability
- [x] Add candidate-plan comparison showing:
  - strategy label
  - selected / rejected status
  - score
  - KPI projections
  - approval flag
  - selection reason
- [x] Add critic summary and findings section when available.
- [x] Add reflection memory section with:
  - latest note
  - lessons
  - pattern tags
  - history list
- [x] Keep the current demo flow pages working unchanged.

## Testing Approach

- [x] Add tests for pipeline graph content and node status mapping.
- [x] Add tests for candidate-plan visualization data.
- [x] Add tests for reflection-memory visualization data.
- [x] Verify presenter compatibility by running `tests/test_demo_presenter.py`.
- [x] Run `./.venv/bin/ruff check ui tests`
- [x] Run `./.venv/bin/pytest -q tests/test_agent_visualization_ui.py tests/test_demo_presenter.py`
- [x] Run `./.venv/bin/pytest -q`
