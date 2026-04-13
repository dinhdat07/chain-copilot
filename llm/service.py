from __future__ import annotations

import json
import re
from typing import Any

from core.models import (
    Action,
    AgentProposal,
    CandidatePlanDraft,
    CandidatePlanEvaluation,
    DecisionLog,
    Event,
    Plan,
    ReflectionNote,
    ScenarioRun,
    SystemState,
)
from llm.config import load_settings
from llm.gemini_client import GeminiClient, GeminiClientError
from orchestrator.prompts import (
    DECISION_EXPLANATION_PROMPT,
    AI_CANDIDATE_PLANNER_PROMPT,
    CRITIC_PROMPT,
    HUMAN_APPROVAL_PROMPT,
    LLM_ENRICHMENT_PROMPT,
    PLANNER_PROMPT,
    REFLECTION_PROMPT,
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

PLANNER_CANDIDATES_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_plans": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "strategy_label": {"type": "string"},
                    "action_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["strategy_label", "action_ids", "rationale"],
            },
        }
    },
    "required": ["candidate_plans"],
}

CRITIC_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["summary", "findings"],
}

REFLECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "lessons": {
            "type": "array",
            "items": {"type": "string"},
        },
        "pattern_tags": {
            "type": "array",
            "items": {"type": "string"},
        },
        "follow_up_checks": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["summary", "lessons", "pattern_tags", "follow_up_checks"],
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


def _call_json_model(
    *,
    prompt: str,
    schema: dict,
    capability: str = "general",
    model_override: str | None = None,
) -> tuple[dict | None, str | None, str | None]:
    settings = load_settings()
    if not settings.enabled:
        return None, None, None
    if capability == "planner" and settings.planner_mode == "deterministic":
        return None, settings.provider, "planner_mode=deterministic"
    if settings.provider != "gemini":
        return None, settings.provider, f"unsupported provider: {settings.provider}"
    last_error: str | None = None
    client = GeminiClient(settings)
    for attempt in range(1, settings.retry_attempts + 1):
        try:
            response = client.generate_json(
                prompt=prompt,
                schema=schema,
                model_override=model_override,
            )
        except GeminiClientError as exc:
            last_error = str(exc)
            if attempt >= settings.retry_attempts:
                break
            continue
        return response, settings.provider, None
    return None, settings.provider, last_error


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


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _normalize_strategy_label(raw_value: str, rationale: str = "") -> str:
    value = raw_value.strip().lower()
    normalized = _normalize_text(raw_value)
    rationale_normalized = _normalize_text(rationale)
    if value in {"cost_first", "balanced", "resilience_first"}:
        return value
    alias_map = {
        "costfirst": "cost_first",
        "costoptimized": "cost_first",
        "costplan": "cost_first",
        "plana": "cost_first",
        "strategya": "cost_first",
        "optiona": "cost_first",
        "balanced": "balanced",
        "balancedplan": "balanced",
        "planb": "balanced",
        "strategyb": "balanced",
        "optionb": "balanced",
        "resiliencefirst": "resilience_first",
        "resilientfirst": "resilience_first",
        "resilienceplan": "resilience_first",
        "planc": "resilience_first",
        "strategyc": "resilience_first",
        "optionc": "resilience_first",
    }
    if normalized in alias_map:
        return alias_map[normalized]
    if "cost" in normalized:
        return "cost_first"
    if "balanc" in normalized:
        return "balanced"
    if "resilien" in normalized or "recover" in normalized:
        return "resilience_first"
    if "cost" in rationale_normalized:
        return "cost_first"
    if "balance" in rationale_normalized:
        return "balanced"
    if any(
        token in rationale_normalized
        for token in {"resilien", "recover", "service", "stockout"}
    ):
        return "resilience_first"
    return raw_value.strip().lower()


def _action_aliases(action: Action) -> set[str]:
    aliases = {
        action.action_id,
        action.action_id.lower(),
        _normalize_text(action.action_id),
        action.target_id.lower(),
        _normalize_text(action.target_id),
        f"{action.action_type.value}:{action.target_id}".lower(),
        _normalize_text(f"{action.action_type.value}:{action.target_id}"),
        _normalize_text(f"{action.action_type.value} {action.target_id}"),
        _normalize_text(action.reason),
    }
    supplier_id = action.parameters.get("supplier_id")
    route_id = action.parameters.get("route_id")
    quantity = action.parameters.get("quantity")
    if supplier_id:
        aliases.add(str(supplier_id).lower())
        aliases.add(_normalize_text(str(supplier_id)))
        aliases.add(_normalize_text(f"{action.target_id} {supplier_id}"))
    if route_id:
        aliases.add(str(route_id).lower())
        aliases.add(_normalize_text(str(route_id)))
        aliases.add(_normalize_text(f"{action.target_id} {route_id}"))
    if quantity is not None:
        aliases.add(_normalize_text(f"{action.target_id} {quantity}"))
    return {alias for alias in aliases if alias}


def _action_alias_map(candidate_actions: list[Action]) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for action in candidate_actions:
        for alias in _action_aliases(action):
            alias_map.setdefault(alias, action.action_id)
    return alias_map


def _extract_candidate_action_refs(item: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    direct_fields = [
        item.get("action_ids"),
        item.get("recommended_action_ids"),
        item.get("selected_actions"),
        item.get("actions"),
    ]
    for field in direct_fields:
        if isinstance(field, list):
            for value in field:
                if isinstance(value, dict):
                    for key in ("action_id", "id", "ref", "name"):
                        if value.get(key):
                            refs.append(str(value[key]))
                            break
                elif value is not None:
                    refs.append(str(value))
    return refs


def _build_specialist_prompt(
    *,
    agent_name: str,
    state: SystemState,
    event: Event | None,
    proposal: AgentProposal,
    state_slice: dict[str, Any],
    custom_prompt: str | None = None,
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

    agent_instruction = (
        custom_prompt.format(agent_name=agent_name)
        if custom_prompt
        else SPECIALIST_AGENT_PROMPT.format(agent_name=agent_name)
    )

    instructions = "\n\n".join(
        [
            agent_instruction,
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


def _build_planner_candidates_prompt(
    *,
    state: SystemState,
    event: Event | None,
    candidate_actions: list[Action],
) -> str:
    context = {
        "mode": state.mode.value,
        "active_events": [_event_context(item) for item in state.active_events],
        "trigger_event": _event_context(event),
        "kpis": state.kpis.model_dump(mode="json"),
        "specialist_outputs": {
            name: {
                "observations": output.observations,
                "risks": output.risks,
                "domain_summary": output.domain_summary,
                "downstream_impacts": output.downstream_impacts,
                "recommended_action_ids": output.recommended_action_ids,
                "tradeoffs": output.tradeoffs,
                "notes_for_planner": output.notes_for_planner,
            }
            for name, output in state.agent_outputs.items()
            if name != "planner"
        },
        "candidate_actions": _action_catalog(candidate_actions),
    }
    instructions = [
        AI_CANDIDATE_PLANNER_PROMPT.strip(),
        PLANNER_PROMPT.strip(),
    ]
    if state.mode.value == "crisis":
        from orchestrator.prompts import CRISIS_MODE_PROMPT

        instructions.append(CRISIS_MODE_PROMPT.strip())
    instructions.append(
        "Return JSON with candidate_plans containing exactly these strategy_label values: "
        "cost_first, balanced, resilience_first. Only use action ids from candidate_actions."
    )
    instructions.append(
        "Allowed planner output shape example: "
        '{"candidate_plans":[{"strategy_label":"cost_first","action_ids":["act_x"],"rationale":"..."},'
        '{"strategy_label":"balanced","action_ids":["act_y"],"rationale":"..."},'
        '{"strategy_label":"resilience_first","action_ids":["act_z"],"rationale":"..."}]}'
    )
    instruction_text = "\n\n".join(instructions)
    return f"{instruction_text}\n\nContext:\n{json.dumps(context, ensure_ascii=True, indent=2)}"


def _build_critic_prompt(
    *,
    state: SystemState,
    event: Event | None,
    selected_plan: Plan,
    evaluations: list[CandidatePlanEvaluation],
) -> str:
    context = {
        "mode": state.mode.value,
        "active_events": [_event_context(item) for item in state.active_events],
        "trigger_event": _event_context(event),
        "selected_plan": {
            "plan_id": selected_plan.plan_id,
            "strategy_label": selected_plan.strategy_label,
            "approval_required": selected_plan.approval_required,
            "approval_reason": selected_plan.approval_reason,
            "score": selected_plan.score,
            "score_breakdown": selected_plan.score_breakdown,
            "action_ids": [action.action_id for action in selected_plan.actions],
        },
        "candidate_evaluations": [
            evaluation.model_dump(mode="json") for evaluation in evaluations
        ],
    }
    instructions = "\n\n".join(
        [
            CRITIC_PROMPT.strip(),
            "Return JSON with keys summary and findings. Keep findings concise and grounded in the evaluated candidates.",
        ]
    )
    return f"{instructions}\n\nContext:\n{json.dumps(context, ensure_ascii=True, indent=2)}"


def _build_reflection_prompt(
    *,
    state: SystemState,
    run: ScenarioRun,
    decision_log: DecisionLog | None,
) -> str:
    context = {
        "scenario_run": run.model_dump(mode="json"),
        "active_events": [_event_context(item) for item in state.active_events],
        "current_kpis": state.kpis.model_dump(mode="json"),
        "latest_plan": state.latest_plan.model_dump(mode="json")
        if state.latest_plan
        else None,
        "latest_decision": decision_log.model_dump(mode="json")
        if decision_log
        else None,
    }
    instructions = "\n\n".join(
        [
            REFLECTION_PROMPT.strip(),
            (
                "Return JSON with keys summary, lessons, pattern_tags, follow_up_checks. "
                "Keep each field concise and grounded in the actual outcome."
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


def _apply_ranked_actions(
    proposal: AgentProposal, ranked_action_ids: list[str]
) -> None:
    if not ranked_action_ids:
        return
    by_id = {action.action_id: action for action in proposal.proposals}
    ranked_actions = [
        by_id[action_id] for action_id in ranked_action_ids if action_id in by_id
    ]
    if not ranked_actions:
        return
    current_max = max((action.priority for action in proposal.proposals), default=0.0)
    top_priority = min(1.0, current_max + 0.1)
    for index, action in enumerate(ranked_actions):
        action.priority = round(max(0.0, top_priority - (index * 0.03)), 4)
    unranked_actions = [
        action
        for action in proposal.proposals
        if action.action_id not in ranked_action_ids
    ]
    proposal.proposals = ranked_actions + unranked_actions


def enrich_specialist_proposal(
    *,
    agent_name: str,
    state: SystemState,
    event: Event | None,
    proposal: AgentProposal,
    state_slice: dict[str, Any],
    custom_prompt: str | None = None,
) -> None:
    prompt = _build_specialist_prompt(
        agent_name=agent_name,
        state=state,
        event=event,
        proposal=proposal,
        state_slice=state_slice,
        custom_prompt=custom_prompt,
    )

    settings = load_settings()
    model_override = settings.agent_models.get(agent_name)

    response, provider, error = _call_json_model(
        prompt=prompt,
        schema=SPECIALIST_SCHEMA,
        capability="specialist",
        model_override=model_override,
    )
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
        str(item).strip() for item in response.get("tradeoffs", []) if str(item).strip()
    ]
    notes_for_planner = str(response.get("notes_for_planner", "")).strip()
    if notes_for_planner:
        proposal.notes_for_planner = notes_for_planner

    allowed_ids = {action.action_id for action in proposal.proposals}
    ranked_action_ids = _unique_action_ids(
        [
            str(item).strip()
            for item in response.get("recommended_action_ids", [])
            if str(item).strip()
        ],
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
        proposal.llm_error = (
            proposal.llm_error or f"{provider} returned an empty specialist response"
        )


def generate_candidate_plan_drafts(
    *,
    state: SystemState,
    event: Event | None,
    candidate_actions: list[Action],
) -> tuple[list[CandidatePlanDraft], str | None]:
    prompt = _build_planner_candidates_prompt(
        state=state,
        event=event,
        candidate_actions=candidate_actions,
    )

    settings = load_settings()
    model_override = settings.agent_models.get("planner")

    response, _, error = _call_json_model(
        prompt=prompt,
        schema=PLANNER_CANDIDATES_SCHEMA,
        capability="planner",
        model_override=model_override,
    )
    if response is None:
        return [], error

    allowed_ids = {action.action_id for action in candidate_actions}
    alias_map = _action_alias_map(candidate_actions)
    drafts: list[CandidatePlanDraft] = []
    for item in response.get("candidate_plans", []):
        rationale = str(item.get("rationale", "")).strip()
        strategy_label = _normalize_strategy_label(
            str(item.get("strategy_label", "")).strip(), rationale
        )
        extracted_refs = _extract_candidate_action_refs(item)
        action_ids = _unique_action_ids(
            [
                alias_map.get(
                    candidate_ref,
                    alias_map.get(_normalize_text(candidate_ref), candidate_ref),
                )
                for candidate_ref in extracted_refs
                if candidate_ref.strip()
            ],
            allowed_ids,
        )
        drafts.append(
            CandidatePlanDraft(
                strategy_label=strategy_label,
                action_ids=action_ids,
                rationale=rationale,
                llm_used=True,
            )
        )
    return drafts, None


def critique_candidate_plans(
    *,
    state: SystemState,
    event: Event | None,
    selected_plan: Plan,
    evaluations: list[CandidatePlanEvaluation],
) -> tuple[str | None, list[str], bool, str | None]:
    prompt = _build_critic_prompt(
        state=state,
        event=event,
        selected_plan=selected_plan,
        evaluations=evaluations,
    )

    settings = load_settings()
    model_override = settings.agent_models.get("critic")

    response, _, error = _call_json_model(
        prompt=prompt,
        schema=CRITIC_SCHEMA,
        capability="critic",
        model_override=model_override,
    )
    if response is None:
        return None, [], False, error
    summary = str(response.get("summary", "")).strip() or None
    findings = [
        str(item).strip() for item in response.get("findings", []) if str(item).strip()
    ]
    used = bool(summary or findings)
    return summary, findings, used, None


def generate_reflection_note(
    *,
    state: SystemState,
    run: ScenarioRun,
    decision_log: DecisionLog | None,
) -> tuple[ReflectionNote | None, str | None]:
    prompt = _build_reflection_prompt(
        state=state,
        run=run,
        decision_log=decision_log,
    )
    response, _, error = _call_json_model(
        prompt=prompt,
        schema=REFLECTION_SCHEMA,
        capability="reflection",
    )
    if response is None:
        return None, error
    note = ReflectionNote(
        note_id=f"note_{run.run_id}",
        run_id=run.run_id,
        scenario_id=run.scenario_id,
        plan_id=run.result_plan_id,
        event_types=[event.type.value for event in run.events],
        mode=state.mode.value,
        approval_status=run.approval_status or "unknown",
        summary=str(response.get("summary", "")).strip(),
        lessons=[
            str(item).strip()
            for item in response.get("lessons", [])
            if str(item).strip()
        ],
        pattern_tags=[
            str(item).strip()
            for item in response.get("pattern_tags", [])
            if str(item).strip()
        ],
        follow_up_checks=[
            str(item).strip()
            for item in response.get("follow_up_checks", [])
            if str(item).strip()
        ],
        llm_used=True,
        llm_error=None,
    )
    return note, None


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

    model_override = settings.agent_models.get("planner")
    decision_log.llm_model = model_override if model_override else settings.model

    if settings.provider != "gemini":
        decision_log.llm_used = False
        decision_log.llm_error = f"unsupported provider: {settings.provider}"
        return

    prompt = _build_prompt(
        state=state, event=event, plan=plan, decision_log=decision_log
    )
    try:
        response = GeminiClient(settings).generate_json(
            prompt=prompt,
            schema=ENRICHMENT_SCHEMA,
            model_override=model_override,
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
    decision_log.llm_used = any(
        [planner_narrative, operator_explanation, approval_summary]
    )
    decision_log.llm_error = None

