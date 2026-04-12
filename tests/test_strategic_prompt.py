"""
Tests for Strategic Planner Agent Memory & Prompt System.
"""
from datetime import datetime, timezone

from core.enums import EventType, Mode, ActionType
from core.models import Action, Event, HistoricalCase, MemorySnapshot, Plan
from core.state import default_memory
from policies.strategic_prompt import (
    retrieve_relevant_cases,
    compute_memory_influence,
    derive_strategy_rationale,
    build_strategic_prompt,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_event(event_type: EventType = EventType.SUPPLIER_DELAY, severity: float = 0.8) -> Event:
    now = datetime.now(timezone.utc)
    return Event(
        event_id="evt_test_001",
        type=event_type,
        source="test",
        severity=severity,
        occurred_at=now,
        detected_at=now,
        dedupe_key="test_001",
    )


def _make_memory_with_cases() -> MemorySnapshot:
    return default_memory()


def _make_action(action_type: ActionType = ActionType.REORDER) -> Action:
    return Action(
        action_id="act_reorder_SKU_1",
        action_type=action_type,
        target_id="SKU_1",
        reason="test action",
        priority=0.7,
    )


# ------------------------------------------------------------------
# Test 1: retrieve_relevant_cases returns top matching cases
# ------------------------------------------------------------------

def test_retrieve_relevant_cases_matches_by_type() -> None:
    memory = _make_memory_with_cases()
    event = _make_event(EventType.SUPPLIER_DELAY, severity=0.8)
    
    cases = retrieve_relevant_cases(event, memory, top_k=3)
    
    assert len(cases) == 3
    # Top cases should be supplier_delay type (CASE_2024_001, CASE_2024_004)
    top_types = [c.event_type for c in cases[:2]]
    assert "supplier_delay" in top_types


def test_retrieve_relevant_cases_limits_results() -> None:
    memory = _make_memory_with_cases()
    event = _make_event(EventType.ROUTE_BLOCKAGE, severity=0.7)
    
    cases = retrieve_relevant_cases(event, memory, top_k=2)
    assert len(cases) == 2


def test_retrieve_relevant_cases_scores_similarity() -> None:
    memory = _make_memory_with_cases()
    event = _make_event(EventType.SUPPLIER_DELAY, severity=0.8)
    
    cases = retrieve_relevant_cases(event, memory, top_k=5)
    # Case_2024_001 is supplier_delay with severity=0.8 — exact match should be highest
    top_case = cases[0]
    assert top_case.case_id == "CASE_2024_001"
    assert top_case.similarity_score > 0.9


def test_retrieve_returns_empty_if_no_memory() -> None:
    event = _make_event()
    cases = retrieve_relevant_cases(event, memory=None, top_k=3)
    assert cases == []


def test_retrieve_returns_empty_if_no_event() -> None:
    memory = _make_memory_with_cases()
    cases = retrieve_relevant_cases(event=None, memory=memory, top_k=3)
    assert cases == []


# ------------------------------------------------------------------
# Test 2: compute_memory_influence
# ------------------------------------------------------------------

def test_memory_influence_is_zero_if_no_cases() -> None:
    score = compute_memory_influence([])
    assert score == 0.0


def test_memory_influence_is_high_for_high_similarity() -> None:
    memory = _make_memory_with_cases()
    event = _make_event(EventType.SUPPLIER_DELAY, severity=0.8)
    cases = retrieve_relevant_cases(event, memory)
    score = compute_memory_influence(cases)
    assert 0.5 <= score <= 1.0


def test_memory_influence_is_between_0_and_1() -> None:
    memory = _make_memory_with_cases()
    event = _make_event(EventType.DEMAND_SPIKE, severity=0.3)
    cases = retrieve_relevant_cases(event, memory)
    score = compute_memory_influence(cases)
    assert 0.0 <= score <= 1.0


# ------------------------------------------------------------------
# Test 3: build_strategic_prompt
# ------------------------------------------------------------------

def test_prompt_contains_all_blocks() -> None:
    memory = _make_memory_with_cases()
    event = _make_event(EventType.SUPPLIER_DELAY, severity=0.8)
    cases = retrieve_relevant_cases(event, memory, top_k=3)
    actions = [_make_action()]
    
    prompt = build_strategic_prompt(
        mode="crisis",
        event=event,
        historical_cases=cases,
        candidate_actions=actions,
    )
    
    assert "CURRENT DISRUPTION" in prompt
    assert "HISTORICAL MEMORY" in prompt
    assert "SPECIALIST AGENT PROPOSALS" in prompt
    assert "HARD CONSTRAINTS" in prompt
    assert "TASK INSTRUCTIONS" in prompt


def test_prompt_references_case_ids() -> None:
    memory = _make_memory_with_cases()
    event = _make_event(EventType.SUPPLIER_DELAY, severity=0.8)
    cases = retrieve_relevant_cases(event, memory, top_k=2)
    
    prompt = build_strategic_prompt(
        mode="normal",
        event=event,
        historical_cases=cases,
        candidate_actions=[],
    )
    
    assert "CASE_2024_001" in prompt


def test_prompt_mode_directive_changes_by_mode() -> None:
    memory = _make_memory_with_cases()
    event = _make_event()
    cases = []
    
    crisis_prompt = build_strategic_prompt("crisis", event, cases, [])
    normal_prompt = build_strategic_prompt("normal", event, cases, [])
    
    assert "SERVICE LEVEL" in crisis_prompt
    assert "COST EFFICIENCY" in normal_prompt


# ------------------------------------------------------------------
# Test 4: derive_strategy_rationale
# ------------------------------------------------------------------

def test_rationale_includes_event_info() -> None:
    event = _make_event(EventType.SUPPLIER_DELAY, severity=0.8)
    rationale = derive_strategy_rationale(event, [], [])
    assert "supplier_delay" in rationale
    assert "80%" in rationale


def test_rationale_includes_case_references() -> None:
    memory = _make_memory_with_cases()
    event = _make_event(EventType.SUPPLIER_DELAY, severity=0.8)
    cases = retrieve_relevant_cases(event, memory, top_k=2)
    actions = [_make_action()]
    
    rationale = derive_strategy_rationale(event, cases, actions)
    
    assert "CASE_2024_001" in rationale
    assert "reorder" in rationale.lower()


def test_rationale_without_event() -> None:
    rationale = derive_strategy_rationale(None, [], [])
    assert "No historical cases" in rationale


# ------------------------------------------------------------------
# Test 5: default_memory seed cases are correct
# ------------------------------------------------------------------

def test_default_memory_has_seed_cases() -> None:
    memory = default_memory()
    assert len(memory.historical_cases) >= 8


def test_default_memory_case_ids_are_unique() -> None:
    memory = default_memory()
    ids = [c.case_id for c in memory.historical_cases]
    assert len(ids) == len(set(ids))


def test_default_memory_all_event_types_covered() -> None:
    memory = default_memory()
    event_types = {c.event_type for c in memory.historical_cases}
    assert "supplier_delay" in event_types
    assert "route_blockage" in event_types
    assert "demand_spike" in event_types
    assert "compound" in event_types
