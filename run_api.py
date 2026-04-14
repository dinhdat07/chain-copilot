from __future__ import annotations

import os
from pathlib import Path

import uvicorn


BASE_DIR = Path(__file__).resolve().parent
RELOAD_DIR_NAMES = (
    "actions",
    "agents",
    "app_api",
    "core",
    "llm",
    "orchestrator",
    "policies",
    "simulation",
)


def build_reload_dirs() -> list[str]:
    return [
        str(directory)
        for directory in (BASE_DIR / name for name in RELOAD_DIR_NAMES)
        if directory.exists()
    ]


if __name__ == "__main__":
    uvicorn.run(
        "api:app",
        host=os.getenv("CHAINCOPILOT_API_HOST", "127.0.0.1"),
        port=int(os.getenv("CHAINCOPILOT_API_PORT", "8000")),
        reload=True,
        reload_dirs=build_reload_dirs(),
        env_file=".env",
    )
