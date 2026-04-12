# Execution Dispatch Lifecycle

## Objective

Turn execution records from one-shot summaries into a coherent simulation-backed lifecycle that survives approval transitions and safer-plan replacements.

## Scope

- [x] Extend execution contracts with transition history and receipts
- [x] Reuse and update the pending execution record through approval resolution
- [x] Cancel superseded executions when a safer plan is requested
- [x] Expose latest execution details in approval command responses
- [x] Add tests for auto-apply, approve, reject, and safer-plan flows

## Files To Modify

- [x] `docs/internal/feat-execution-dispatch-lifecycle.md`
- [x] `core/runtime_records.py`
- [x] `core/runtime_tracking.py`
- [x] `core/memory.py`
- [x] `app_api/schemas.py`
- [x] `app_api/services.py`
- [x] `tests/test_execution_dispatch_lifecycle.py`

## Implementation Steps

- [x] Add execution transition model and store it in `ExecutionRecord`
- [x] Build helpers to create, advance, and cancel execution records
- [x] On initial plan selection, create execution with `planned -> approval_pending` or `planned -> applied`
- [x] On approval, advance the same execution to `approved -> applied`
- [x] On rejection, advance the same execution to `cancelled`
- [x] On safer plan, cancel the old execution and create a new one for the replacement plan
- [x] Surface execution details in API payloads without breaking existing fields

## Testing Approach

- [x] Daily plan creates an applied execution with history
- [x] Crisis approval run creates approval-pending execution
- [x] Approve updates the existing execution instead of creating an unrelated one
- [x] Reject cancels the existing execution
- [x] Safer plan cancels the old execution and issues a new one
