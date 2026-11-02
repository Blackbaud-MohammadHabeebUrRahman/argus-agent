"""Scenario definitions: one incident, mocked tool responses, and the
ground truth the agent should reach.

A scenario is a single YAML file. The format is designed to be
hand-writable — operators who see a real production incident should be
able to turn it into a regression test for the agent in under 15
minutes.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from argus.models import Incident


class MockToolResponse(BaseModel):
    """What the mock tool returns when called with matching args.

    ``args_match`` is a dict of expected argument values. A rule matches
    when every key in ``args_match`` equals the corresponding value in
    the agent's call. An empty ``args_match`` matches every call — use
    it as a catch-all fallback at the end of a rule list.
    """

    args_match: dict[str, Any] = Field(default_factory=dict)
    response: Any


class ExpectedBehavior(BaseModel):
    """What the grader looks for in the agent's output and trajectory."""

    must_mention_in_root_cause: list[str] = Field(default_factory=list)
    must_mention_in_actions: list[str] = Field(default_factory=list)
    must_mention_anywhere: list[str] = Field(default_factory=list)
    must_call_tools: list[str] = Field(default_factory=list)
    must_not_call_tools: list[str] = Field(default_factory=list)
    judge_criteria: str = ""


class Budgets(BaseModel):
    max_tool_calls: int = 15
    max_cost_usd: float = 0.50
    max_duration_s: float = 120.0


class Scenario(BaseModel):
    """One eval case."""

    name: str
    description: str = ""
    incident: Incident
    mock_tools: dict[str, list[MockToolResponse]] = Field(default_factory=dict)
    expected: ExpectedBehavior = Field(default_factory=ExpectedBehavior)
    budgets: Budgets = Field(default_factory=Budgets)
    products: list[str] | None = None

    def mock_responses_for(self, tool_name: str) -> list[MockToolResponse]:
        return self.mock_tools.get(tool_name, [])


def load_scenario(path: Path) -> Scenario:
    raw = yaml.safe_load(path.read_text())
    return Scenario.model_validate(raw)


def load_scenarios(fixtures_dir: Path) -> list[Scenario]:
    """Load every ``.yaml`` under a directory, sorted by filename.

    Deterministic order makes diffs between eval runs legible.
    """
    paths = sorted(fixtures_dir.glob("*.yaml"))
    return [load_scenario(p) for p in paths]


def _ensure_dt(value: Any) -> datetime:
    """Accept 'YYYY-MM-DD HH:MM:SSZ' as a shorthand in fixture YAML."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
