# Service Observability And Reliability

## Objective

Finish the minimum production-service slice of Task G by exposing stable service flags and metrics, standardizing error envelopes, and hardening LLM reliability with bounded retries and deterministic degradation.

## Scope

- [x] Inspect existing service contracts, runtime records, and LLM fallback behavior
- [x] Add typed service runtime contracts for feature flags and observability metrics
- [x] Standardize API error envelopes for validation, application, and system failures
- [x] Add bounded LLM retry behavior while preserving deterministic fallback paths
- [x] Expose runtime flags and service metrics through API
- [x] Add focused tests for flags, metrics, retries, and standardized errors

## Files To Modify

- [x] `docs/internal/feat-service-observability-reliability.md`
- [x] `api.py`
- [x] `app_api/routers.py`
- [x] `app_api/schemas.py`
- [x] `app_api/services.py`
- [x] `core/memory.py`
- [x] `core/runtime_tracking.py`
- [x] `llm/config.py`
- [x] `llm/service.py`
- [x] `tests/test_service_observability_reliability.py`

## Implementation Steps

- [x] Add service settings and API view models for planner mode, dispatch mode, and LLM flags
- [x] Add store helpers and service aggregation for run metrics, agent latency, fallback rate, approval rate, and execution failure rate
- [x] Register FastAPI exception handlers that always return the typed error envelope
- [x] Add limited LLM retry attempts before returning deterministic fallback behavior
- [x] Add a service runtime endpoint exposing flags and metrics
- [x] Verify existing API and run-ledger flows stay green

## Testing Approach

- [x] Service runtime endpoint returns stable flags and computed metrics
- [x] Missing resources and validation errors return the standardized error envelope
- [x] Planner deterministic mode skips planner LLM calls safely
- [x] LLM retry attempts are bounded and still degrade predictably on failure
- [x] Existing backend alignment, run history, execution lifecycle, and policy tests remain green
