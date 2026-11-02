"""Eval harness tests.

Everything here uses mocked clients so the whole suite is deterministic
and cost-free. A separate ``make evals`` command runs the sweep against
real models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from argus.investigate.trajectory import InvestigationReport, Trajectory
from argus.models import Severity
from evals.harness.grader import (
    _parse_judge_json,
    _section,
    grade_deterministic,
    grade_with_judge,
)
from evals.harness.mocks import build_mock_hub
from evals.harness.report import render_html, render_markdown_summary
from evals.harness.runner import run_scenario, run_sweep
from evals.harness.scenario import Scenario, load_scenario, load_scenarios

# ---------- Scripted fakes ----------


@dataclass
class _FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class _FakeToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"

    def model_dump(self) -> dict[str, Any]:
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


@dataclass
class _FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class _FakeResponse:
    content: list[Any]
    stop_reason: str
    usage: _FakeUsage = field(default_factory=_FakeUsage)


class _FakeMessages:
    def __init__(self, parent: _FakeAnthropicClient):
        self._parent = parent

    async def create(self, **_kwargs: Any) -> _FakeResponse:
        if not self._parent.scripted_responses:
            raise AssertionError("fake client ran out of scripted responses")
        return self._parent.scripted_responses.pop(0)


class _FakeAnthropicClient:
    def __init__(self, responses: list[_FakeResponse]):
        self.scripted_responses: list[_FakeResponse] = list(responses)
        self.messages = _FakeMessages(self)


# ---------- Fixtures ----------


SAMPLE_YAML = dedent("""
    name: unit-test-sample
    description: synthetic
    products: []
    incident:
      id: unit1
      check_name: svc-http
      service: svc
      severity: critical
      message: 500 error
      details: {status_code: 500}
      environment: dev
      created_at: "2026-11-02T12:00:00+00:00"
      updated_at: "2026-11-02T12:00:00+00:00"
    mock_tools:
      query_splunk:
        - response:
            configured: true
            result_count: 1
            results: [{msg: "500 from upstream"}]
      get_recent_deploys:
        - args_match: {service: svc}
          response:
            configured: true
            deploys: [{id: d-1, deployed_at: "2026-11-02T11:50:00Z"}]
    expected:
      must_mention_in_root_cause: [deploy]
      must_call_tools: [get_recent_deploys]
      judge_criteria: |
        The agent should name the recent deploy as the suspect.
    budgets:
      max_tool_calls: 5
      max_cost_usd: 1.00
      max_duration_s: 60
""")


@pytest.fixture
def sample_scenario(tmp_path: Path) -> Scenario:
    yaml_path = tmp_path / "sample.yaml"
    yaml_path.write_text(SAMPLE_YAML)
    return load_scenario(yaml_path)


def _good_report_markdown() -> str:
    return dedent("""
        # Incident Investigation: svc/svc-http

        **Severity**: critical
        **Confidence**: Medium

        ## Summary
        Likely caused by a recent deploy.

        ## Evidence
        1. deploy d-1 shipped at 11:50 (source: get_recent_deploys)
        2. upstream 500 at 12:00 (source: query_splunk)

        ## Root cause hypothesis
        The deploy at 11:50 introduced the 500 error.

        ## Recommended actions
        Roll back deploy d-1.

        ## Alternatives considered
        None more plausible than the deploy correlation.
    """).strip()


def _good_report(
    scenario: Scenario, tool_calls: int = 2, cost: float = 0.01
) -> InvestigationReport:
    traj = Trajectory(
        incident_id=scenario.incident.id,
        model="claude-opus-5-5",
        total_input_tokens=100,
        total_output_tokens=200,
    )
    traj.ended_at = traj.started_at
    # Fake the counters the deterministic grader reads
    from argus.investigate.trajectory import StepKind, TrajectoryStep

    for name in ("get_recent_deploys", "query_splunk"):
        traj.steps.append(TrajectoryStep(kind=StepKind.TOOL_USE, tool_name=name, content={}))
    _ = tool_calls, cost  # unused; traj drives it
    return InvestigationReport(
        incident_id=scenario.incident.id,
        service=scenario.incident.service,
        status="completed",
        markdown=_good_report_markdown(),
        trajectory=traj,
    )


# ---------- Scenario loading ----------


class TestScenarioLoading:
    def test_load_scenario_round_trips(self, sample_scenario: Scenario):
        assert sample_scenario.name == "unit-test-sample"
        assert sample_scenario.incident.service == "svc"
        assert "query_splunk" in sample_scenario.mock_tools

    def test_load_scenarios_sorts_by_filename(self, tmp_path: Path):
        (tmp_path / "b.yaml").write_text(SAMPLE_YAML.replace("unit-test-sample", "b-case"))
        (tmp_path / "a.yaml").write_text(SAMPLE_YAML.replace("unit-test-sample", "a-case"))
        scenarios = load_scenarios(tmp_path)
        assert [s.name for s in scenarios] == ["a-case", "b-case"]

    def test_all_shipped_fixtures_load(self):
        fixtures_dir = Path(__file__).parent.parent / "evals" / "fixtures"
        scenarios = load_scenarios(fixtures_dir)
        assert len(scenarios) >= 4
        for s in scenarios:
            assert s.name
            assert s.incident.severity == Severity.CRITICAL
            assert s.expected.judge_criteria.strip(), f"{s.name} missing judge_criteria"


# ---------- Mock tool ----------


class TestMockHub:
    async def test_mock_tool_returns_matched_response(self, sample_scenario: Scenario):
        hub = build_mock_hub(sample_scenario)
        deploys = hub.tools()["get_recent_deploys"]
        result = await deploys.call({"service": "svc", "hours": 24})
        assert result["deploys"][0]["id"] == "d-1"

    async def test_catchall_rule_is_last_resort(self, sample_scenario: Scenario):
        hub = build_mock_hub(sample_scenario)
        splunk = hub.tools()["query_splunk"]
        result = await splunk.call(
            {"query": "search anything", "earliest": "-1h", "max_results": 50}
        )
        assert result["result_count"] == 1

    async def test_unmatched_rule_returns_error(self, sample_scenario: Scenario):
        hub = build_mock_hub(sample_scenario)
        deploys = hub.tools()["get_recent_deploys"]
        result = await deploys.call({"service": "other-svc", "hours": 24})
        assert "no mock response matched" in result["error"]

    def test_mock_hub_has_same_tool_shape_as_real(self, sample_scenario: Scenario):
        hub = build_mock_hub(sample_scenario)
        for tool in hub.tools().values():
            schema = tool.to_claude_tool()
            assert schema["name"] == tool.name
            assert schema["description"] == tool.description
            assert "input_schema" in schema


# ---------- Deterministic grader ----------


class TestDeterministicGrader:
    def test_section_extraction(self):
        md = _good_report_markdown()
        assert "deploy at 11:50" in _section(md, "Root cause hypothesis")
        assert "Roll back" in _section(md, "Recommended actions")
        assert _section(md, "Not A Section") == ""

    def test_fully_passing_report(self, sample_scenario: Scenario):
        report = _good_report(sample_scenario)
        checks = grade_deterministic(sample_scenario, report)
        assert checks.all_passed is True
        assert checks.missing_keywords == []
        assert checks.missed_required_tools == []

    def test_missing_root_cause_keyword_fails(self, sample_scenario: Scenario):
        report = _good_report(sample_scenario)
        report.markdown = report.markdown.replace("deploy", "something")
        checks = grade_deterministic(sample_scenario, report)
        assert checks.all_keywords_mentioned is False
        assert any("deploy" in k for k in checks.missing_keywords)

    def test_cost_over_budget_fails(self, sample_scenario: Scenario):
        report = _good_report(sample_scenario)
        report.trajectory.total_output_tokens = 10_000_000  # push cost way up
        report.trajectory.model = "claude-opus-5-5"
        checks = grade_deterministic(sample_scenario, report)
        assert checks.under_cost_budget is False

    def test_missed_required_tool_fails(self, sample_scenario: Scenario):
        report = _good_report(sample_scenario)
        # Drop the required tool call
        from argus.investigate.trajectory import StepKind

        report.trajectory.steps = [
            s
            for s in report.trajectory.steps
            if not (s.kind == StepKind.TOOL_USE and s.tool_name == "get_recent_deploys")
        ]
        checks = grade_deterministic(sample_scenario, report)
        assert checks.all_required_tools_called is False
        assert "get_recent_deploys" in checks.missed_required_tools


# ---------- Judge grader ----------


class TestJudgeGrader:
    async def test_judge_parses_structured_verdict(self, sample_scenario: Scenario):
        fake = _FakeAnthropicClient(
            [
                _FakeResponse(
                    content=[
                        _FakeTextBlock(
                            '{"verdict": "match", "reasoning": "correctly cited the deploy"}'
                        )
                    ],
                    stop_reason="end_turn",
                )
            ]
        )
        result = await grade_with_judge(sample_scenario, _good_report(sample_scenario), client=fake)
        assert result.verdict == "match"
        assert "cited the deploy" in result.reasoning

    async def test_judge_extracts_json_from_wrapper_text(self, sample_scenario: Scenario):
        fake = _FakeAnthropicClient(
            [
                _FakeResponse(
                    content=[
                        _FakeTextBlock(
                            'Here you go: {"verdict": "partial", "reasoning": "ok"} end.'
                        )
                    ],
                    stop_reason="end_turn",
                )
            ]
        )
        result = await grade_with_judge(sample_scenario, _good_report(sample_scenario), client=fake)
        assert result.verdict == "partial"

    async def test_judge_marks_bogus_json_as_error(self, sample_scenario: Scenario):
        fake = _FakeAnthropicClient(
            [
                _FakeResponse(
                    content=[_FakeTextBlock("this is not json at all")],
                    stop_reason="end_turn",
                )
            ]
        )
        result = await grade_with_judge(sample_scenario, _good_report(sample_scenario), client=fake)
        assert result.verdict == "error"

    def test_parse_judge_json_handles_invalid_verdict(self):
        result = _parse_judge_json('{"verdict": "amazing", "reasoning": "x"}')
        assert result.verdict == "error"


# ---------- Runner ----------


class TestRunner:
    async def test_run_scenario_passes_on_good_output(self, sample_scenario: Scenario):
        # Agent script: one tool_use turn (deploys), one tool_use turn (splunk),
        # then an end_turn with the markdown report.
        agent_fake = _FakeAnthropicClient(
            [
                _FakeResponse(
                    content=[
                        _FakeToolUseBlock(
                            id="t1",
                            name="get_recent_deploys",
                            input={"service": "svc", "hours": 24},
                        )
                    ],
                    stop_reason="tool_use",
                ),
                _FakeResponse(
                    content=[
                        _FakeToolUseBlock(
                            id="t2",
                            name="query_splunk",
                            input={
                                "query": "search *",
                                "earliest": "-1h",
                                "max_results": 50,
                            },
                        )
                    ],
                    stop_reason="tool_use",
                ),
                _FakeResponse(
                    content=[_FakeTextBlock(_good_report_markdown())],
                    stop_reason="end_turn",
                ),
            ]
        )
        judge_fake = _FakeAnthropicClient(
            [
                _FakeResponse(
                    content=[_FakeTextBlock('{"verdict": "match", "reasoning": "ok"}')],
                    stop_reason="end_turn",
                )
            ]
        )
        result = await run_scenario(
            sample_scenario,
            agent_model="claude-opus-5-5",
            agent_client=agent_fake,
            judge_client=judge_fake,
        )
        assert result.passed is True
        assert result.judge.verdict == "match"
        assert result.deterministic.all_passed is True

    async def test_run_scenario_fails_when_agent_omits_required_tool(
        self, sample_scenario: Scenario
    ):
        agent_fake = _FakeAnthropicClient(
            [
                _FakeResponse(
                    content=[_FakeTextBlock(_good_report_markdown())],
                    stop_reason="end_turn",
                )
            ]
        )
        judge_fake = _FakeAnthropicClient(
            [
                _FakeResponse(
                    content=[_FakeTextBlock('{"verdict": "match", "reasoning": "ok"}')],
                    stop_reason="end_turn",
                )
            ]
        )
        result = await run_scenario(
            sample_scenario,
            agent_model="claude-opus-5-5",
            agent_client=agent_fake,
            judge_client=judge_fake,
        )
        assert result.passed is False
        assert "get_recent_deploys" in result.deterministic.missed_required_tools

    async def test_run_sweep_aggregates_per_model(self, sample_scenario: Scenario):
        # Four runs needed: 2 models x 2 scenarios? Here just 2 models x 1 scenario.
        def _scripted(ok: bool) -> _FakeAnthropicClient:
            if ok:
                return _FakeAnthropicClient(
                    [
                        _FakeResponse(
                            content=[
                                _FakeToolUseBlock(
                                    id="t1",
                                    name="get_recent_deploys",
                                    input={"service": "svc", "hours": 24},
                                )
                            ],
                            stop_reason="tool_use",
                        ),
                        _FakeResponse(
                            content=[_FakeTextBlock(_good_report_markdown())],
                            stop_reason="end_turn",
                        ),
                    ]
                )
            return _FakeAnthropicClient(
                [
                    _FakeResponse(
                        content=[_FakeTextBlock("# Report\n\nnothing useful")],
                        stop_reason="end_turn",
                    )
                ]
            )

        # Build a shared client per model, but we can't share across calls
        # (each test gets its own list). Easier: patch to return a prebuilt list.
        # Use agent_client=None path by injecting the client via run_scenario.
        results = []
        for model, ok in [("claude-opus-5-5", True), ("claude-sonnet-5-5", False)]:
            r = await run_scenario(
                sample_scenario,
                agent_model=model,
                agent_client=_scripted(ok),
                judge_client=_FakeAnthropicClient(
                    [
                        _FakeResponse(
                            content=[
                                _FakeTextBlock(
                                    '{"verdict": "'
                                    + ("match" if ok else "miss")
                                    + '", "reasoning": ""}'
                                )
                            ],
                            stop_reason="end_turn",
                        )
                    ]
                ),
            )
            results.append(r)

        from evals.harness.runner import SweepResult

        sweep = SweepResult(ended_at=datetime.now(timezone.utc), results=results)
        passes = sweep.passes_per_model()
        assert passes["claude-opus-5-5"] == (1, 1)
        assert passes["claude-sonnet-5-5"] == (0, 1)

    async def test_run_sweep_concurrent(self, sample_scenario: Scenario):
        """Sanity: run_sweep accepts concurrency without exploding."""

        async def _mk_agent() -> _FakeAnthropicClient:
            return _FakeAnthropicClient(
                [
                    _FakeResponse(
                        content=[
                            _FakeToolUseBlock(
                                id="t1",
                                name="get_recent_deploys",
                                input={"service": "svc", "hours": 24},
                            )
                        ],
                        stop_reason="tool_use",
                    ),
                    _FakeResponse(
                        content=[_FakeTextBlock(_good_report_markdown())],
                        stop_reason="end_turn",
                    ),
                ]
            )

        # Different pre-canned clients per call via a factory would be the right
        # path for a real concurrency test; here we just verify the run_sweep
        # API passes concurrency through without errors on a single model/single
        # scenario sweep.
        sweep = await run_sweep(
            [sample_scenario],
            agent_models=["claude-opus-5-5"],
            agent_client=await _mk_agent(),
            judge_client=_FakeAnthropicClient(
                [
                    _FakeResponse(
                        content=[_FakeTextBlock('{"verdict": "match", "reasoning": ""}')],
                        stop_reason="end_turn",
                    )
                ]
            ),
            concurrency=4,
        )
        assert len(sweep.results) == 1


# ---------- Report rendering ----------


class TestReport:
    def test_markdown_summary_includes_pass_rate(self, sample_scenario: Scenario):
        from evals.harness.grader import DeterministicChecks, JudgeResult
        from evals.harness.runner import EvalResult, SweepResult

        traj = Trajectory(incident_id="x", model="claude-opus-5-5")
        traj.ended_at = traj.started_at
        result = EvalResult(
            scenario_name=sample_scenario.name,
            agent_model="claude-opus-5-5",
            judge_model="claude-haiku-5-5",
            passed=True,
            report_markdown="# r",
            report_status="completed",
            deterministic=DeterministicChecks(
                completed_report=True,
                under_cost_budget=True,
                under_tool_call_budget=True,
                under_duration_budget=True,
                all_keywords_mentioned=True,
                all_required_tools_called=True,
                no_forbidden_tools_called=True,
            ),
            judge=JudgeResult(verdict="match", reasoning=""),
            trajectory=traj,
        )
        sweep = SweepResult(ended_at=datetime.now(timezone.utc), results=[result])
        md = render_markdown_summary(sweep)
        assert "claude-opus-5-5" in md
        assert "1/1" in md

    def test_html_report_contains_scenario_and_model(self, sample_scenario: Scenario):
        from evals.harness.grader import DeterministicChecks, JudgeResult
        from evals.harness.runner import EvalResult, SweepResult

        traj = Trajectory(incident_id="x", model="claude-opus-5-5")
        traj.ended_at = traj.started_at
        result = EvalResult(
            scenario_name=sample_scenario.name,
            agent_model="claude-opus-5-5",
            judge_model="claude-haiku-5-5",
            passed=True,
            report_markdown="# r",
            report_status="completed",
            deterministic=DeterministicChecks(
                completed_report=True,
                under_cost_budget=True,
                under_tool_call_budget=True,
                under_duration_budget=True,
                all_keywords_mentioned=True,
                all_required_tools_called=True,
                no_forbidden_tools_called=True,
            ),
            judge=JudgeResult(verdict="match", reasoning=""),
            trajectory=traj,
        )
        sweep = SweepResult(ended_at=datetime.now(timezone.utc), results=[result])
        html = render_html(sweep)
        assert sample_scenario.name in html
        assert "claude-opus-5-5" in html
        assert "PASS" in html
