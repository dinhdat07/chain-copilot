from __future__ import annotations

import re
from typing import Any

DISPLAY_TEXT_FIELDS = {
    "approval_reason",
    "critic_summary",
    "detail",
    "domain_summary",
    "failure_reason",
    "fallback_reason",
    "llm_error",
    "llm_fallback_reason",
    "llm_planner_narrative",
    "message",
    "mode_rationale",
    "notes_for_planner",
    "planner_reasoning",
    "projection_summary",
    "rationale",
    "reason",
    "reflection_notes",
    "selection_reason",
    "strategy_rationale",
    "summary",
    "tradeoff",
    "dominant_constraint",
}

DISPLAY_TEXT_LIST_FIELDS = {
    "compensation_hints",
    "critic_findings",
    "downstream_impacts",
    "follow_up_checks",
    "key_changes",
    "lessons",
    "observations",
    "risks",
    "tradeoffs",
    "winning_factors",
}

_LINE_PREFIX_RE = re.compile(
    r"^(?P<prefix>\s*(?:(?:[-*+•]|\d+[.)])\s+|>\s+)*)"
    r"(?P<quotes>[\"'“‘(\[]*)"
    r"(?P<body>.*)$"
)


def normalize_display_text(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    return "".join(_normalize_line(line) for line in value.splitlines(keepends=True))


def normalize_display_list(values: list[str]) -> list[str]:
    return [normalize_display_text(item) or "" for item in values]


def normalize_display_payload(value: Any, *, field_name: str | None = None) -> Any:
    if isinstance(value, str):
        if field_name is None or field_name in DISPLAY_TEXT_FIELDS:
            return normalize_display_text(value)
        return value

    if isinstance(value, list):
        if field_name in DISPLAY_TEXT_LIST_FIELDS:
            return [
                normalize_display_text(item) if isinstance(item, str) else normalize_display_payload(item)
                for item in value
            ]
        return [normalize_display_payload(item) for item in value]

    if isinstance(value, dict):
        return {
            key: normalize_display_payload(item, field_name=key)
            for key, item in value.items()
        }

    return value


def _normalize_line(line: str) -> str:
    newline = ""
    if line.endswith("\r\n"):
        newline = "\r\n"
        line = line[:-2]
    elif line.endswith("\n"):
        newline = "\n"
        line = line[:-1]

    if not line:
        return newline

    match = _LINE_PREFIX_RE.match(line)
    if match is None:
        return f"{line}{newline}"

    prefix = match.group("prefix")
    quotes = match.group("quotes")
    body = match.group("body")
    if not body:
        return f"{line}{newline}"

    token = _leading_token(body)
    if token and (any(char.isdigit() for char in token) or "_" in token):
        return f"{line}{newline}"

    first_char = body[0]
    if not (first_char.isalpha() and first_char.islower()):
        return f"{line}{newline}"

    normalized = f"{prefix}{quotes}{first_char.upper()}{body[1:]}"
    return f"{normalized}{newline}"


def _leading_token(value: str) -> str:
    token_chars: list[str] = []
    for char in value:
        if char.isspace() or char in {".", ",", ";", ":", "!", "?"}:
            break
        token_chars.append(char)
    return "".join(token_chars)
