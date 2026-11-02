"""Grading: deterministic checks + Haiku-as-judge for the narrative.

Deterministic grading catches the easy regressions — did the agent
blow the token budget, did it skip a tool it clearly needed, did its
output name the thing the scenario said it should name. It's cheap and
precise but misses the subtle quality questions ("did it actually
understand the problem"), which is what the judge is for.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from argus.investigate.trajectory import InvestigationReport, StepKind

if TYPE_CHECKING:
    from .scenario import Scenario

logger = logging.getLogger(__name__)


JudgeVerdict = Literal["match", "partial", "miss", "error"]

DEFAULT_JUDGE_MODEL = "claude-haiku-5-5"


class DeterministicChecks(BaseModel):
    """Which gates the report passed. Each field is a boolean per check."""

    completed_report: bool
    under_cost_budget: bool
    under_tool_call_budget: bool
    under_duration_budget: bool
    all_keywords_mentioned: bool
    all_required_tools_called: bool
    no_forbidden_tools_called: bool

    missing_keywords: list[str] = Field(default_factory=list)
    missed_required_tools: list[str] = Field(default_factory=list)
    forbidden_tools_called: list[str] = Field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return (
            self.completed_report
            and self.under_cost_budget
            and self.under_tool_call_budget
            and self.under_duration_budget
            and self.all_keywords_mentioned
            and self.all_required_tools_called
            and self.no_forbidden_tools_called
        )


class JudgeResult(BaseModel):
    verdict: JudgeVerdict
    reasoning: str = ""


def _section(markdown: str, heading: str) -> str:
    """Return the body of a '## heading' section, or empty if missing."""
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s+|\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(markdown)
    return match.group(1).strip() if match else ""


def grade_deterministic(scenario: Scenario, report: InvestigationReport) -> DeterministicChecks:
    traj = report.trajectory
    markdown = report.markdown or ""

    completed = report.status == "completed"
    under_cost = traj.estimated_cost_usd <= scenario.budgets.max_cost_usd
    under_calls = traj.tool_call_count <= scenario.budgets.max_tool_calls
    under_duration = traj.duration_seconds <= scenario.budgets.max_duration_s

    root_cause = _section(markdown, "Root cause hypothesis")
    actions = _section(markdown, "Recommended actions")

    missing_keywords: list[str] = []
    for kw in scenario.expected.must_mention_in_root_cause:
        if kw.lower() not in root_cause.lower():
            missing_keywords.append(f"root_cause:{kw}")
    for kw in scenario.expected.must_mention_in_actions:
        if kw.lower() not in actions.lower():
            missing_keywords.append(f"actions:{kw}")
    for kw in scenario.expected.must_mention_anywhere:
        if kw.lower() not in markdown.lower():
            missing_keywords.append(f"anywhere:{kw}")

    called_tools = {
        step.tool_name for step in traj.steps if step.kind == StepKind.TOOL_USE and step.tool_name
    }
    missed_required = [
        name for name in scenario.expected.must_call_tools if name not in called_tools
    ]
    forbidden_called = [
        name for name in scenario.expected.must_not_call_tools if name in called_tools
    ]

    return DeterministicChecks(
        completed_report=completed,
        under_cost_budget=under_cost,
        under_tool_call_budget=under_calls,
        under_duration_budget=under_duration,
        all_keywords_mentioned=not missing_keywords,
        all_required_tools_called=not missed_required,
        no_forbidden_tools_called=not forbidden_called,
        missing_keywords=missing_keywords,
        missed_required_tools=missed_required,
        forbidden_tools_called=forbidden_called,
    )


_JUDGE_PROMPT = """\
You are grading an SRE agent's incident investigation report. Produce ONE JSON \
object with keys 'verdict' and 'reasoning'. 'verdict' must be exactly one of \
'match', 'partial', or 'miss'. No prose outside the JSON.

- 'match': the report identifies the expected root cause and recommends \
appropriate actions.
- 'partial': the report is on the right track but misses important details, \
has minor errors, or shows the right reasoning without naming the specific \
cause.
- 'miss': the report identifies the wrong cause, or is empty/unhelpful.

Scenario incident:
{incident_summary}

Expected diagnosis:
{judge_criteria}

Agent report:
---
{agent_markdown}
---

Return ONLY the JSON object."""


def _incident_summary(scenario: Scenario) -> str:
    i = scenario.incident
    return (
        f"- Service: {i.service}\n"
        f"- Check: {i.check_name}\n"
        f"- Severity: {i.severity.value}\n"
        f"- Message: {i.message}"
    )


def _parse_judge_json(text: str) -> JudgeResult:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return JudgeResult(verdict="error", reasoning=f"no JSON in: {text[:200]}")
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            return JudgeResult(verdict="error", reasoning=f"bad JSON: {exc}")
    verdict = obj.get("verdict", "error")
    if verdict not in ("match", "partial", "miss"):
        verdict = "error"
    return JudgeResult(verdict=verdict, reasoning=str(obj.get("reasoning", "")))


async def grade_with_judge(
    scenario: Scenario,
    report: InvestigationReport,
    *,
    client: Any = None,
    model: str = DEFAULT_JUDGE_MODEL,
) -> JudgeResult:
    """Ask a cheap model whether the agent's narrative matches expectations."""
    if not scenario.expected.judge_criteria:
        return JudgeResult(verdict="match", reasoning="(no judge criteria set)")
    if client is None:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic()
    prompt = _JUDGE_PROMPT.format(
        incident_summary=_incident_summary(scenario),
        judge_criteria=scenario.expected.judge_criteria,
        agent_markdown=report.markdown or "(empty report)",
    )
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        logger.exception("judge call raised")
        return JudgeResult(verdict="error", reasoning=f"judge error: {exc}")
    text_parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if isinstance(block, dict):
            if block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
        elif getattr(block, "type", "") == "text":
            text_parts.append(getattr(block, "text", "") or "")
    return _parse_judge_json("\n".join(text_parts))
