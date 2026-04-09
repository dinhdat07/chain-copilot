from __future__ import annotations

import json

from core.models import DecisionLog, Event, Plan, SystemState
from llm.config import load_settings
from llm.gemini_client import GeminiClient, GeminiClientError
from orchestrator.prompts import (
    DECISION_EXPLANATION_PROMPT,
    HUMAN_APPROVAL_PROMPT,
    LLM_ENRICHMENT_PROMPT,
    PLANNER_PROMPT,
)


ENRICHMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "planner_narrative": {"type": "string"},
        "operator_explanation": {"type": "string"},
        "approval_summary": {"type": "string"},
    },
    "required": [
        "planner_narrative",
        "operator_explanation",
        "approval_summary",
    ],
}


def _event_context(event: Event | None) -> dict:
    if event is None:
        return {}
    return {
        "event_id": event.event_id,
        "type": event.type.value,
        "severity": event.severity,
        "entity_ids": event.entity_ids,
        "payload": event.payload,
    }


def _build_prompt(
    *,
    state: SystemState,
    event: Event | None,
    plan: Plan,
    decision_log: DecisionLog,
) -> str:
    context = {
        "mode": state.mode.value,
        "active_events": [_event_context(item) for item in state.active_events],
        "trigger_event": _event_context(event),
        "plan": {
            "plan_id": plan.plan_id,
            "score": plan.score,
            "score_breakdown": plan.score_breakdown,
            "approval_required": plan.approval_required,
            "approval_reason": plan.approval_reason,
            "selected_actions": [
                {
                    "action_id": action.action_id,
                    "action_type": action.action_type.value,
                    "target_id": action.target_id,
                    "reason": action.reason,
                    "estimated_cost_delta": action.estimated_cost_delta,
                    "estimated_service_delta": action.estimated_service_delta,
                    "estimated_risk_delta": action.estimated_risk_delta,
                    "estimated_recovery_hours": action.estimated_recovery_hours,
                }
                for action in plan.actions
            ],
        },
        "decision_log": {
            "decision_id": decision_log.decision_id,
            "before_kpis": decision_log.before_kpis.model_dump(mode="json"),
            "after_kpis": decision_log.after_kpis.model_dump(mode="json"),
            "rejected_actions": decision_log.rejected_actions,
            "winning_factors": decision_log.winning_factors,
            "deterministic_rationale": decision_log.rationale,
        },
    }
    instructions = "\n\n".join(
        [
            PLANNER_PROMPT.strip(),
            DECISION_EXPLANATION_PROMPT.strip(),
            HUMAN_APPROVAL_PROMPT.strip(),
            LLM_ENRICHMENT_PROMPT.strip(),
            (
                "Return JSON with keys planner_narrative, operator_explanation, approval_summary. "
                "Use only the provided facts. Keep each field concise. If no approval is required, "
                "set approval_summary to an empty string."
            ),
        ]
    )
    return f"{instructions}\n\nContext:\n{json.dumps(context, ensure_ascii=True, indent=2)}"


def enrich_plan_and_decision(
    *,
    state: SystemState,
    event: Event | None,
    plan: Plan,
    decision_log: DecisionLog,
) -> None:
    settings = load_settings()
    if not settings.enabled:
        decision_log.llm_used = False
        decision_log.llm_provider = None
        decision_log.llm_model = None
        decision_log.llm_error = None
        plan.llm_planner_narrative = None
        return

    decision_log.llm_provider = settings.provider
    decision_log.llm_model = settings.model
    if settings.provider != "gemini":
        decision_log.llm_used = False
        decision_log.llm_error = f"unsupported provider: {settings.provider}"
        return

    prompt = _build_prompt(state=state, event=event, plan=plan, decision_log=decision_log)
    try:
        response = GeminiClient(settings).generate_json(
            prompt=prompt,
            schema=ENRICHMENT_SCHEMA,
        )
    except GeminiClientError as exc:
        decision_log.llm_used = False
        decision_log.llm_error = str(exc)
        plan.llm_planner_narrative = None
        return

    planner_narrative = str(response.get("planner_narrative", "")).strip()
    operator_explanation = str(response.get("operator_explanation", "")).strip()
    approval_summary = str(response.get("approval_summary", "")).strip()

    plan.llm_planner_narrative = planner_narrative or None
    decision_log.llm_operator_explanation = operator_explanation or None
    decision_log.llm_approval_summary = approval_summary or None
    decision_log.llm_used = any([planner_narrative, operator_explanation, approval_summary])
    decision_log.llm_error = None
