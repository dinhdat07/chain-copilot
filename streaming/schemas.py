from __future__ import annotations

from typing import Any, Literal

from datetime import datetime
from pydantic import BaseModel, Field


ThinkingEventType = Literal[
    "start",        # Starting process
    "analysis",     # Analyzing data
    "thinking",     # Reasoning / Considering
    "decision",     # Making interim decision
    "action",       # Performing action (dispatch, apply)
    "observation",  # Receiving results from agent / tool
    "reflection",   # Critic evaluating the plan
    "final",        # Final conclusion — trace complete
    "error",        # Unexpected system error
]


class ThinkingEvent(BaseModel):
    """
    A thinking/action step of the multi-agent system,
    streamed in real-time via WebSocket to the UI.

    Example:
        ThinkingEvent(
            type="thinking",
            agent="planner",
            step="strategy_generation",
            message="Generating 3 strategies: cost_first, balanced, resilience_first",
            data={"strategies": 3, "candidate_count": 12},
        )
    """

    type: ThinkingEventType
    agent: str = Field(
        description="Agent name emitting the event: 'risk' | 'demand' | 'inventory' | "
        "'supplier' | 'logistics' | 'planner' | 'critic' | 'system'"
    )
    step: str = Field(
        description="Short step name in snake_case, e.g., 'event_scan', 'plan_selected'"
    )
    message: str = Field(
        description="Human-readable description of current task — used directly on UI"
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Detailed metadata, agent-specific",
    )
    run_id: str | None = Field(
        default=None,
        description="run_id of the current orchestration cycle, auto-assigned by EventBus",
    )
    sequence: int = Field(
        default=0,
        description="Order of the event in the run — auto-incremented by EventBus",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="ISO timestamp of when the event was emitted",
    )
