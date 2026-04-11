from __future__ import annotations

import os
from dataclasses import dataclass


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LLMSettings:
    enabled: bool
    provider: str
    api_key: str | None
    model: str
    timeout_s: float


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
    )
