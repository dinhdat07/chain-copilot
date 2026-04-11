# Contracts

## RunRecord

```json
{
  "run_id": "run_1234abcd",
  "run_type": "event_response",
  "parent_run_id": "run_prev123",
  "correlation_id": "corr_supplier_delay_1",
  "trigger_event_id": "evt_env_001",
  "input_event_ids": ["evt_supplier_delay_001"],
  "mode_before": "normal",
  "mode_after": "crisis",
  "status": "completed",
  "started_at": "2026-04-11T10:00:00Z",
  "completed_at": "2026-04-11T10:00:02Z",
  "duration_ms": 2000.0,
  "decision_id": "dec_1234abcd",
  "selected_plan_id": "plan_1234abcd",
  "execution_id": "exec_1234abcd",
  "approval_status": "pending",
  "llm_fallback_used": true,
  "llm_fallback_reason": "llm_disabled",
  "selected_plan_summary": {
    "plan_id": "plan_1234abcd",
    "strategy_label": "balanced",
    "generated_by": "hybrid_fallback",
    "approval_required": true,
    "approval_reason": "event severity exceeds approval threshold",
    "score": 0.271,
    "action_ids": ["act_supplier_A", "act_reroute_B"]
  },
  "execution_summary": {
    "status": "approval_pending",
    "dispatch_mode": "simulation",
    "action_ids": ["act_supplier_A", "act_reroute_B"]
  }
}
```

## EventEnvelope

```json
{
  "event_id": "evt_env_1234abcd",
  "event_class": "domain",
  "event_type": "supplier_delay",
  "source": "api",
  "occurred_at": "2026-04-11T10:00:00Z",
  "ingested_at": "2026-04-11T10:00:01Z",
  "correlation_id": "corr_supplier_delay_1",
  "causation_id": null,
  "idempotency_key": "supplier_delay:sku_1:sup_a",
  "severity": 0.9,
  "entity_ids": ["SKU_1", "SUP_A"],
  "payload": {
    "supplier_id": "SUP_A",
    "sku": "SKU_1",
    "delay_hours": 48
  }
}
```

## TraceStep

```json
{
  "step_id": "step_1234abcd",
  "sequence": 3,
  "node_key": "supplier",
  "node_type": "agent",
  "status": "completed",
  "started_at": "2026-04-11T10:00:01Z",
  "completed_at": "2026-04-11T10:00:01.400Z",
  "duration_ms": 400.0,
  "mode_snapshot": "crisis",
  "summary": "supplier options ranked for SKU_1",
  "reasoning_source": "ai_assisted_reasoning",
  "input_snapshot": {},
  "output_snapshot": {},
  "observations": [],
  "risks": [],
  "downstream_impacts": [],
  "recommended_action_ids": ["act_supplier_SKU_1_SUP_B"],
  "tradeoffs": [],
  "llm_used": true,
  "llm_error": null,
  "fallback_used": false,
  "fallback_reason": null
}
```

## ExecutionRecord

```json
{
  "execution_id": "exec_1234abcd",
  "run_id": "run_1234abcd",
  "decision_id": "dec_1234abcd",
  "plan_id": "plan_1234abcd",
  "status": "approval_pending",
  "dispatch_mode": "simulation",
  "dry_run": false,
  "target_system": "digital_twin",
  "action_ids": ["act_supplier_A", "act_reroute_B"],
  "receipts": [],
  "failure_reason": null,
  "created_at": "2026-04-11T10:00:02Z",
  "updated_at": "2026-04-11T10:00:02Z"
}
```

## API Examples

### `POST /api/v1/events/ingest`

Request:

```json
{
  "event_class": "domain",
  "event_type": "supplier_delay",
  "source": "api",
  "severity": 0.9,
  "entity_ids": ["SKU_1", "SUP_A"],
  "payload": {
    "supplier_id": "SUP_A",
    "sku": "SKU_1",
    "delay_hours": 48
  }
}
```

Response:

```json
{
  "event": {
    "event_id": "evt_env_1234abcd",
    "event_class": "domain",
    "event_type": "supplier_delay",
    "source": "api",
    "occurred_at": "2026-04-11T10:00:00Z",
    "ingested_at": "2026-04-11T10:00:01Z",
    "correlation_id": "corr_supplier_delay_1",
    "causation_id": null,
    "idempotency_key": "supplier_delay:sku_1:sup_a",
    "severity": 0.9,
    "entity_ids": ["SKU_1", "SUP_A"],
    "payload": {
      "supplier_id": "SUP_A",
      "sku": "SKU_1",
      "delay_hours": 48
    }
  },
  "run_id": "run_1234abcd",
  "accepted": true,
  "execution_id": "exec_1234abcd"
}
```

### `GET /api/v1/runs/{run_id}`

Response:

```json
{
  "item": {
    "run_id": "run_1234abcd",
    "run_type": "event_response",
    "status": "completed"
  }
}
```

### `GET /api/v1/runs/{run_id}/trace`

Response:

```json
{
  "item": {
    "run_id": "run_1234abcd",
    "trace_id": "trace_1234abcd",
    "status": "completed",
    "steps": []
  }
}
```

### `GET /api/v1/execution/{execution_id}`

Response:

```json
{
  "item": {
    "execution_id": "exec_1234abcd",
    "status": "approval_pending",
    "dispatch_mode": "simulation"
  }
}
```
