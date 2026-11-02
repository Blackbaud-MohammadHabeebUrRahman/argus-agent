"""Serializable record of what the investigation agent did and saw.

Everything the agent does — model calls, tool calls, their inputs and
outputs, tokens, latency — lands here. Writing this out as JSON
alongside the human-readable report means Phase 4's eval harness can
re-grade past investigations without re-running them, and makes every
investigation reproducible: feed the trajectory back to the agent, and
it should reach the same conclusion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class StepKind(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"


class TrajectoryStep(BaseModel):
    """A single step in the investigation."""

    kind: StepKind
    content: Any
    tool_name: str | None = None
    tool_use_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: float = 0.0
    is_error: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Rough blended rates per million tokens — close enough for a "did this cost
# $0.02 or $2" sanity check. Numbers come straight from the model table and
# don't account for caching. Phase 4 can swap in real post-hoc billing.
_MODEL_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.00, 50.00),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = _MODEL_PRICING_PER_MTOK.get(model)
    if not rates:
        return 0.0
    in_rate, out_rate = rates
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate


class Trajectory(BaseModel):
    """Full record of one investigation. Serializable; replayable in Phase 4."""

    incident_id: str
    model: str
    steps: list[TrajectoryStep] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    stop_reason: str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    @property
    def estimated_cost_usd(self) -> float:
        return estimate_cost_usd(self.model, self.total_input_tokens, self.total_output_tokens)

    @property
    def tool_call_count(self) -> int:
        return sum(1 for s in self.steps if s.kind == StepKind.TOOL_USE)

    @property
    def duration_seconds(self) -> float:
        end = self.ended_at or datetime.now(timezone.utc)
        return (end - self.started_at).total_seconds()


class InvestigationReport(BaseModel):
    """What the agent returns to the operator."""

    incident_id: str
    service: str
    status: Literal["completed", "stopped_at_limit", "errored", "empty"]
    markdown: str
    trajectory: Trajectory

    def to_summary(self) -> str:
        return (
            f"Investigation {self.status} for {self.incident_id} ({self.service}): "
            f"{self.trajectory.tool_call_count} tool calls, "
            f"{self.trajectory.total_input_tokens}+{self.trajectory.total_output_tokens} tokens, "
            f"${self.trajectory.estimated_cost_usd:.4f}, "
            f"{self.trajectory.duration_seconds:.1f}s"
        )
