from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

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


def _parse_env_line(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None
    if value and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return key, value


@lru_cache(maxsize=1)
def _load_dotenv_file() -> None:
    autoload_flag = os.getenv("CHAINCOPILOT_AUTOLOAD_DOTENV")
    if autoload_flag is not None and autoload_flag.strip().lower() in {"0", "false", "no", "off"}:
        return
    if autoload_flag is None and ("pytest" in sys.modules or os.getenv("PYTEST_CURRENT_TEST")):
        return
    dotenv_path = Path(__file__).resolve().parent.parent / ".env"
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        os.environ.setdefault(key, value)


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
    vertex_project_id: str | None
    vertex_region: str
    agent_models: dict[str, str]


def load_settings() -> LLMSettings:
    _load_dotenv_file()
    provider = os.getenv("CHAINCOPILOT_LLM_PROVIDER", "gemini").strip().lower()
    generic_api_key = os.getenv("CHAINCOPILOT_LLM_API_KEY") or os.getenv("GEMINI_API_KEY")
    vertex_api_key = os.getenv("VERTEX_AI_API_KEY") or generic_api_key
    vertex_project_id = (
        os.getenv("VERTEX_AI_PROJECT_ID")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GOOGLE_CLOUD_PROJECT_ID")
    )
    vertex_region = (
        os.getenv("VERTEX_AI_REGION")
        or os.getenv("GOOGLE_CLOUD_LOCATION")
        or "global"
    ).strip()
    api_key = vertex_api_key if provider == "vertex" else generic_api_key
    timeout_raw = os.getenv("CHAINCOPILOT_LLM_TIMEOUT_S", "4")
    try:
        timeout_s = float(timeout_raw)
    except ValueError:
        timeout_s = 4.0

    agents = [
        "risk",
        "demand",
        "inventory",
        "supplier",
        "logistics",
        "planner",
        "critic",
    ]
    agent_models = {}
    for agent in agents:
        model_env = os.getenv(f"CHAINCOPILOT_{agent.upper()}_LLM_MODEL")
        if model_env:
            agent_models[agent] = model_env.strip()

    return LLMSettings(
        enabled=_env_flag("CHAINCOPILOT_LLM_ENABLED", default=False),
        provider=provider,
        api_key=api_key,
        model=os.getenv("CHAINCOPILOT_LLM_MODEL", "gemini-2.5-flash").strip(),
        timeout_s=max(timeout_s, 1.0),
        retry_attempts=max(_env_int("CHAINCOPILOT_LLM_RETRY_ATTEMPTS", 1), 1),
        planner_mode=_planner_mode(),
        dispatch_mode=_dispatch_mode(),
        vertex_project_id=vertex_project_id,
        vertex_region=vertex_region or "global",
        agent_models=agent_models,
    )
