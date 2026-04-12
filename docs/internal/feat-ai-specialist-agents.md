# Feature Plan: AI Specialist Agents

## Objective

Introduce structured LLM specialist reasoning for risk, demand, supplier, and logistics while keeping deterministic state, action generation, scoring, and execution safety unchanged.

## Scope

- Keep the existing LangGraph flow and agent classes.
- Extend specialist outputs with structured AI fields.
- Build deterministic domain action catalogs first, then let LLM agents interpret and rank those safe options.
- Preserve deterministic fallback when LLM is disabled, times out, or returns invalid action IDs.
- Do not change approval thresholds, KPI math, or action execution logic.

## Files To Modify

- [x] `core/models.py`
- [x] `agents/base.py`
- [x] `agents/risk.py`
- [x] `agents/demand.py`
- [x] `agents/supplier.py`
- [x] `agents/logistics.py`
- [x] `llm/service.py`
- [x] `orchestrator/prompts.py`
- [x] `tests/test_ai_specialist_agents.py`

No changes were required in `agents/inventory.py` or `tests/test_langgraph_paths.py`; compatibility was verified through the existing test suite.

## Implementation Steps

- [x] Extend `AgentProposal` with optional structured fields:
  - `domain_summary`
  - `downstream_impacts`
  - `recommended_action_ids`
  - `tradeoffs`
  - `llm_used`
  - `llm_error`
- [x] Refactor each specialist agent to build its deterministic observations and safe candidate `Action` list first.
- [x] Add specialist LLM prompt builders that take:
  - mode
  - triggering event
  - relevant state slice
  - current KPI snapshot
  - safe candidate action catalog
- [x] Define a shared structured JSON schema for specialist reasoning:
  - risk returns interpretation and downstream concerns
  - demand/supplier/logistics return summary, ranked action IDs, tradeoffs, and planner notes
- [x] Validate returned action IDs strictly against the deterministic action catalog.
- [x] Reorder `proposal.proposals` and rebalance priorities using valid AI-ranked action IDs.
- [x] Fall back to current deterministic proposal ordering if:
  - LLM disabled
  - LLM error
  - empty or invalid output
- [x] Keep inventory agent deterministic while using the extended `AgentProposal` shape unchanged.
- [x] Preserve `state.agent_outputs` and `state.candidate_actions` contracts.

## Testing Approach

- [x] Add tests for specialist AI ranking success path.
- [x] Add tests for invalid returned action IDs falling back safely.
- [x] Add tests for disabled LLM preserving current deterministic behavior.
- [x] Verify LangGraph normal/crisis/approval routing still works after specialist changes.
- [x] Run `./.venv/bin/ruff check agents core llm orchestrator tests`
- [x] Run `./.venv/bin/pytest -q tests/test_ai_specialist_agents.py tests/test_langgraph_paths.py`
- [x] Run `./.venv/bin/pytest -q`
