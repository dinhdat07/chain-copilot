"""
Strategic Planner Agent Prompt Builder.

Builds context-rich prompts for reasoning about supply chain disruptions
using historical memory cases and operational proposals.
"""
from __future__ import annotations

from core.models import Action, Event, HistoricalCase, MemorySnapshot


# ---------------------------------------------------------------------------
# Memory Retrieval
# ---------------------------------------------------------------------------

def retrieve_relevant_cases(
    event: Event | None,
    memory: MemorySnapshot | None,
    top_k: int = 3,
) -> list[HistoricalCase]:
    """
    Retrieve the most relevant historical cases from memory based on
    event type and severity similarity.
    """
    if not memory or not event or not memory.historical_cases:
        return []

    scored = []
    # Handle both Enum and string for safety
    if hasattr(event.type, "value"):
        event_type_str = str(event.type.value).lower().strip()
    else:
        event_type_str = str(event.type).lower().strip()
    
    for case in memory.historical_cases:
        case_type_str = case.event_type.lower().strip()
        type_match = 1.0 if case_type_str == event_type_str else 0.3
        
        severity_diff = abs(case.event_severity - event.severity)
        severity_score = max(0.0, 1.0 - severity_diff)
        
        similarity = round(0.6 * type_match + 0.4 * severity_score, 4)
        case.similarity_score = similarity
        scored.append(case)

    results = sorted(scored, key=lambda c: c.similarity_score, reverse=True)[:top_k]
    
    # Return cases that meet a minimum similarity threshold for relevance
    return [r for r in results if r.similarity_score >= 0.4]


def compute_memory_influence(cases: list[HistoricalCase]) -> float:
    """
    Compute how much memory should influence the plan (0.0 = no memory, 1.0 = full)
    based on average similarity of retrieved cases.
    """
    if not cases:
        return 0.0
    return round(sum(c.similarity_score for c in cases) / len(cases), 4)


# ---------------------------------------------------------------------------
# Prompt Builder
# ---------------------------------------------------------------------------

def _format_event_block(event: Event | None) -> str:
    if not event:
        return "No active disruption detected. Operating under routine conditions."
    return (
        f"Event ID    : {event.event_id}\n"
        f"Type        : {event.type.value}\n"
        f"Source      : {event.source}\n"
        f"Severity    : {event.severity:.0%}\n"
        f"Entities    : {', '.join(event.entity_ids) or 'N/A'}\n"
        f"Occurred At : {event.occurred_at.strftime('%Y-%m-%d %H:%M UTC')}"
    )


def _format_historical_block(cases: list[HistoricalCase]) -> str:
    if not cases:
        return "No relevant historical cases found in memory."
    lines = []
    for case in cases:
        kpi_str = ", ".join(f"{k}: {v:.3f}" for k, v in case.outcome_kpis.items())
        lines.append(
            f"  Case ID       : {case.case_id}\n"
            f"  Event Type    : {case.event_type} (Severity {case.event_severity:.0%})\n"
            f"  Similarity    : {case.similarity_score:.0%}\n"
            f"  Actions Taken : {', '.join(case.actions_taken)}\n"
            f"  Outcome KPIs  : {kpi_str}\n"
            f"  Reflection    : {case.reflection_notes}"
        )
    return "\n\n".join(lines)


def _format_proposals_block(actions: list[Action]) -> str:
    if not actions:
        return "No candidate actions proposed."
    lines = []
    for a in actions:
        lines.append(
            f"  [{a.action_type.value.upper()}] {a.action_id}\n"
            f"    Target   : {a.target_id}\n"
            f"    Priority : {a.priority:.2f}\n"
            f"    Reason   : {a.reason}\n"
            f"    Cost Δ   : {a.estimated_cost_delta:+.2f} | "
            f"Service Δ: {a.estimated_service_delta:+.2f} | "
            f"Risk Δ: {a.estimated_risk_delta:+.2f}"
        )
    return "\n\n".join(lines)


def build_memory_prompt(
    mode: str,
    historical_cases: list[HistoricalCase],
) -> str:
    """
    Build the Strategic Planner Agent reasoning context focusing on directives and memory.
    """
    history_block = _format_historical_block(historical_cases)

    mode_instruction = (
        "Prioritize SERVICE LEVEL and RECOVERY SPEED above all else. Aggressively mitigate risks."
        if mode == "crisis"
        else "Prioritize COST EFFICIENCY and LEAN INVENTORY while maintaining baseline service."
    )

    return f"""
### STRATEGIC DIRECTIVES
- **Current Operating Mode**: {mode.upper()}
- **Core Objective**: {mode_instruction}

### HISTORICAL MEMORY (Lessons Learned)
{history_block}

### REASONING GUIDELINES
1. ANALYZE PATTERNS: Compare current operational data with historical cases above.
2. LEVERAGE SUCCESS: Prioritize actions that led to positive outcome KPIs in similar past scenarios.
3. JUSTIFY DECISIONS: Explicitly cite Case IDs that influenced your choices. For example: "Selected REORDER because in Case_001, a similar action prevented a stockout."
""".strip()


# ---------------------------------------------------------------------------
# Reasoning Parser (deterministic fallback - no LLM required)
# ---------------------------------------------------------------------------

def derive_strategy_rationale(
    event: Event | None,
    historical_cases: list[HistoricalCase],
    selected_actions: list[Action],
) -> str:
    """
    Generate a human-readable rationale string referencing historical cases.
    This is a deterministic fallback when no LLM is connected.
    """
    parts = []

    if event:
        parts.append(
            f"Responding to {event.type.value} (severity {event.severity:.0%}) "
            f"from '{event.source}'."
        )

    if historical_cases:
        refs = []
        for case in historical_cases:
            refs.append(
                f"{case.case_id} ({case.event_type}, similarity {case.similarity_score:.0%}: "
                f"{case.reflection_notes})"
            )
        parts.append("Referenced historical cases: " + "; ".join(refs) + ".")
    else:
        parts.append("No historical cases matched this scenario.")

    if selected_actions:
        action_descs = [f"{a.action_type.value} on {a.target_id}" for a in selected_actions]
        parts.append(f"Selected actions: {', '.join(action_descs)}.")

    return " ".join(parts)
