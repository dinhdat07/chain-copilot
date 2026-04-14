# Branch Plan

## Recommended Sequence

1. `feat/foundation-run-ledger`
2. `feat/execution-dispatch-lifecycle`
3. `feat/policy-constraint-hooks`
4. `feat/memory-retrieval-hooks`

## Parallel Workstreams

### Backend foundation

- runtime records
- persistence
- ingest/run/trace/execution APIs

### Frontend integration

- consume run and execution contracts
- historical trace views
- event ingest workflow

### Decision engine preparation

- add placeholders for feasibility and policy metadata once run contracts are stable

## Merge Order

1. foundation contracts and persistence
2. execution lifecycle enrichment
3. policy outputs
4. memory retrieval
