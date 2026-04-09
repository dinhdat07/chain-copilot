from __future__ import annotations

import json
from typing import Any

from core.models import Action, AgentProposal, DecisionLog, Event, Plan, SystemState
from llm.config import load_settings
from llm.gemini_client import GeminiClient, GeminiClientError
from orchestrator.prompts import (
    DECISION_EXPLANATION_PROMPT,
    HUMAN_APPROVAL_PROMPT,
    LLM_ENRICHMENT_PROMPT,
    PLANNER_PROMPT,
    SPECIALIST_AGENT_PROMPT,
    SPECIALIST_REASONING_PROMPT,
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

SPECIALIST_SCHEMA = {
    "type": "object",
    "properties": {
        "domain_summary": {"type": "string"},
        "downstream_impacts": {
            "type": "array",
            "items": {"type": "string"},
        },
        "recommended_action_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "tradeoffs": {
            "type": "array",
            "items": {"type": "string"},
        },
        "notes_for_planner": {"type": "string"},
    },
    "required": [
        "domain_summary",
        "downstream_impacts",
        "recommended_action_ids",
        "tradeoffs",
        "notes_for_planner",
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


def _call_json_model(*, prompt: str, schema: dict) -> tuple[dict | None, str | None, str | None]:
    settings = load_settings()
    if not settings.enabled:
        return None, None, None
    if settings.provider != "gemini":
        return None, settings.provider, f"unsupported provider: {settings.provider}"
    try:
        response = GeminiClient(settings).generate_json(
            prompt=prompt,
            schema=schema,
        )
    except GeminiClientError as exc:
        return None, settings.provider, str(exc)
    return response, settings.provider, None


def _action_catalog(actions: list[Action]) -> list[dict[str, Any]]:
    return [
        {
            "action_id": action.action_id,
            "action_type": action.action_type.value,
            "target_id": action.target_id,
            "reason": action.reason,
            "priority": action.priority,
            "estimated_cost_delta": action.estimated_cost_delta,
            "estimated_service_delta": action.estimated_service_delta,
            "estimated_risk_delta": action.estimated_risk_delta,
            "estimated_recovery_hours": action.estimated_recovery_hours,
        }
        for action in actions
    ]


def _build_specialist_prompt(
    *,
    agent_name: str,
    state: SystemState,
    event: Event | None,
    proposal: AgentProposal,
    state_slice: dict[str, Any],
) -> str:
    context = {
        "agent": agent_name,
        "mode": state.mode.value,
        "active_events": [_event_context(item) for item in state.active_events],
        "trigger_event": _event_context(event),
        "kpis": state.kpis.model_dump(mode="json"),
        "state_slice": state_slice,
        "current_observations": proposal.observations,
        "current_risks": proposal.risks,
        "candidate_actions": _action_catalog(proposal.proposals),
    }
    instructions = "\n\n".join(
        [
            SPECIALIST_AGENT_PROMPT.format(agent_name=agent_name),
            SPECIALIST_REASONING_PROMPT.strip(),
            (
                "Return JSON with keys domain_summary, downstream_impacts, "
                "recommended_action_ids, tradeoffs, notes_for_planner. "
                "Only reference action_ids that appear in candidate_actions. "
                "If no action is recommended, return an empty recommended_action_ids array."
            ),
        ]
    )
    return f"{instructions}\n\nContext:\n{json.dumps(context, ensure_ascii=True, indent=2)}"


def _unique_action_ids(action_ids: list[str], allowed_ids: set[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for action_id in action_ids:
        if action_id in allowed_ids and action_id not in seen:
            unique.append(action_id)
            seen.add(action_id)
    return unique


def _apply_ranked_actions(proposal: AgentProposal, ranked_action_ids: list[str]) -> None:
    if not ranked_action_ids:
        return
    by_id = {action.action_id: action for action in proposal.proposals}
    ranked_actions = [by_id[action_id] for action_id in ranked_action_ids if action_id in by_id]
    if not ranked_actions:
        return
    current_max = max((action.priority for action in proposal.proposals), default=0.0)
    top_priority = min(1.0, current_max + 0.1)
    for index, action in enumerate(ranked_actions):
        action.priority = round(max(0.0, top_priority - (index * 0.03)), 4)
    unranked_actions = [action for action in proposal.proposals if action.action_id not in ranked_action_ids]
    proposal.proposals = ranked_actions + unranked_actions


def enrich_specialist_proposal(
    *,
    agent_name: str,
    state: SystemState,
    event: Event | None,
    proposal: AgentProposal,
    state_slice: dict[str, Any],
) -> None:
    prompt = _build_specialist_prompt(
        agent_name=agent_name,
        state=state,
        event=event,
        proposal=proposal,
        state_slice=state_slice,
    )
    response, provider, error = _call_json_model(prompt=prompt, schema=SPECIALIST_SCHEMA)
    proposal.llm_used = False
    proposal.llm_error = error
    if response is None:
        return

    proposal.domain_summary = str(response.get("domain_summary", "")).strip()
    proposal.downstream_impacts = [
        str(item).strip()
        for item in response.get("downstream_impacts", [])
        if str(item).strip()
    ]
    proposal.tradeoffs = [
        str(item).strip()
        for item in response.get("tradeoffs", [])
        if str(item).strip()
    ]
    notes_for_planner = str(response.get("notes_for_planner", "")).strip()
    if notes_for_planner:
        proposal.notes_for_planner = notes_for_planner

    allowed_ids = {action.action_id for action in proposal.proposals}
    ranked_action_ids = _unique_action_ids(
        [str(item).strip() for item in response.get("recommended_action_ids", []) if str(item).strip()],
        allowed_ids,
    )
    if response.get("recommended_action_ids") and not ranked_action_ids and allowed_ids:
        proposal.llm_error = "llm returned no valid action ids"
        return

    proposal.recommended_action_ids = ranked_action_ids
    _apply_ranked_actions(proposal, ranked_action_ids)
    proposal.llm_used = any(
        [
            proposal.domain_summary,
            proposal.downstream_impacts,
            proposal.tradeoffs,
            proposal.notes_for_planner,
            proposal.recommended_action_ids,
        ]
    )
    if not proposal.llm_used and provider:
        proposal.llm_error = proposal.llm_error or f"{provider} returned an empty specialist response"


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
