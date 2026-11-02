"""Run scenarios against the agent, optionally across several models.

A single scenario produces one ``EvalResult`` per model. A sweep is a
list of EvalResults — the thing you render as a report, print as a
table, or diff against a baseline.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from argus.investigate.agent import InvestigationAgent
from argus.investigate.trajectory import InvestigationReport, Trajectory

from .grader import (
    DEFAULT_JUDGE_MODEL,
    DeterministicChecks,
    JudgeResult,
    grade_deterministic,
    grade_with_judge,
)
from .mocks import build_mock_hub
from .scenario import Scenario

logger = logging.getLogger(__name__)


class EvalResult(BaseModel):
    scenario_name: str
    agent_model: str
    judge_model: str
    passed: bool
    report_markdown: str
    report_status: str
    deterministic: DeterministicChecks
    judge: JudgeResult
    trajectory: Trajectory
    error: str | None = None


class SweepResult(BaseModel):
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    results: list[EvalResult] = Field(default_factory=list)

    def passes_per_model(self) -> dict[str, tuple[int, int]]:
        """model -> (passed, total)."""
        counts: dict[str, tuple[int, int]] = {}
        for r in self.results:
            passed, total = counts.get(r.agent_model, (0, 0))
            counts[r.agent_model] = (passed + (1 if r.passed else 0), total + 1)
        return counts

    def totals_per_model(self) -> dict[str, dict[str, float]]:
        """model -> {tool_calls, cost_usd, duration_s, input_tokens, output_tokens}."""
        out: dict[str, dict[str, float]] = {}
        for r in self.results:
            agg = out.setdefault(
                r.agent_model,
                {
                    "runs": 0,
                    "tool_calls": 0,
                    "cost_usd": 0.0,
                    "duration_s": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                },
            )
            agg["runs"] += 1
            agg["tool_calls"] += r.trajectory.tool_call_count
            agg["cost_usd"] += r.trajectory.estimated_cost_usd
            agg["duration_s"] += r.trajectory.duration_seconds
            agg["input_tokens"] += r.trajectory.total_input_tokens
            agg["output_tokens"] += r.trajectory.total_output_tokens
        return out


def _passing(deterministic: DeterministicChecks, judge: JudgeResult) -> bool:
    return deterministic.all_passed and judge.verdict in ("match", "partial")


async def run_scenario(
    scenario: Scenario,
    *,
    agent_model: str,
    agent_client: Any = None,
    judge_client: Any = None,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    max_steps: int = 20,
) -> EvalResult:
    hub = build_mock_hub(scenario)
    agent = InvestigationAgent(
        hub,
        model=agent_model,
        client=agent_client,
        max_steps=max_steps,
    )
    try:
        report = await agent.investigate(scenario.incident)
    except Exception as exc:
        logger.exception("agent raised on scenario %s", scenario.name)
        empty_traj = Trajectory(incident_id=scenario.incident.id, model=agent_model)
        empty_traj.ended_at = datetime.now(timezone.utc)
        return EvalResult(
            scenario_name=scenario.name,
            agent_model=agent_model,
            judge_model=judge_model,
            passed=False,
            report_markdown="",
            report_status="errored",
            deterministic=DeterministicChecks(
                completed_report=False,
                under_cost_budget=True,
                under_tool_call_budget=True,
                under_duration_budget=True,
                all_keywords_mentioned=False,
                all_required_tools_called=False,
                no_forbidden_tools_called=True,
            ),
            judge=JudgeResult(verdict="error", reasoning=f"agent crash: {exc}"),
            trajectory=empty_traj,
            error=str(exc),
        )
    return await _grade_and_assemble(
        scenario,
        report,
        agent_model=agent_model,
        judge_model=judge_model,
        judge_client=judge_client,
    )


async def _grade_and_assemble(
    scenario: Scenario,
    report: InvestigationReport,
    *,
    agent_model: str,
    judge_model: str,
    judge_client: Any,
) -> EvalResult:
    deterministic = grade_deterministic(scenario, report)
    judge = await grade_with_judge(scenario, report, client=judge_client, model=judge_model)
    return EvalResult(
        scenario_name=scenario.name,
        agent_model=agent_model,
        judge_model=judge_model,
        passed=_passing(deterministic, judge),
        report_markdown=report.markdown,
        report_status=report.status,
        deterministic=deterministic,
        judge=judge,
        trajectory=report.trajectory,
    )


async def run_sweep(
    scenarios: list[Scenario],
    *,
    agent_models: list[str],
    agent_client: Any = None,
    judge_client: Any = None,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    max_steps: int = 20,
    concurrency: int = 1,
) -> SweepResult:
    sweep = SweepResult()
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(scenario: Scenario, model: str) -> EvalResult:
        async with sem:
            logger.info("running %s against %s", scenario.name, model)
            return await run_scenario(
                scenario,
                agent_model=model,
                agent_client=agent_client,
                judge_client=judge_client,
                judge_model=judge_model,
                max_steps=max_steps,
            )

    tasks = [_one(s, m) for s in scenarios for m in agent_models]
    sweep.results = await asyncio.gather(*tasks)
    sweep.ended_at = datetime.now(timezone.utc)
    return sweep
