from __future__ import annotations

import os
from dataclasses import dataclass

from core.runtime_records import DispatchMode


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _planner_mode() -> str:
    value = os.getenv("CHAINCOPILOT_PLANNER_MODE", "hybrid").strip().lower()
    if value in {"hybrid", "deterministic"}:
        return value
    return "hybrid"


def _dispatch_mode() -> str:
    value = os.getenv("CHAINCOPILOT_DISPATCH_MODE", DispatchMode.SIMULATION.value).strip().lower()
    if value == DispatchMode.SIMULATION.value:
        return value
    return DispatchMode.SIMULATION.value


@dataclass(frozen=True)
class LLMSettings:
    enabled: bool
    provider: str
    api_key: str | None
    model: str
    timeout_s: float
    retry_attempts: int
    planner_mode: str
    dispatch_mode: str


def load_settings() -> LLMSettings:
    api_key = os.getenv("CHAINCOPILOT_LLM_API_KEY") or os.getenv("GEMINI_API_KEY")
    timeout_raw = os.getenv("CHAINCOPILOT_LLM_TIMEOUT_S", "4")
    try:
        timeout_s = float(timeout_raw)
    except ValueError:
        timeout_s = 4.0
    return LLMSettings(
        enabled=_env_flag("CHAINCOPILOT_LLM_ENABLED", default=False),
        provider=os.getenv("CHAINCOPILOT_LLM_PROVIDER", "gemini").strip().lower(),
        api_key=api_key,
        model=os.getenv("CHAINCOPILOT_LLM_MODEL", "gemini-2.5-flash").strip(),
        timeout_s=max(timeout_s, 1.0),
        retry_attempts=max(_env_int("CHAINCOPILOT_LLM_RETRY_ATTEMPTS", 1), 1),
        planner_mode=_planner_mode(),
        dispatch_mode=_dispatch_mode(),
    )
