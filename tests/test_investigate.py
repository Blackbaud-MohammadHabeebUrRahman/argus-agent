"""Investigation agent tests.

Uses a hand-rolled FakeAnthropicClient so the agent loop can be driven
through scripted scenarios without any real API calls — no network, no
tokens burned, no model randomness. The real client's shape (``response.
content`` list of blocks, ``response.stop_reason``, ``response.usage.*``)
is reproduced closely enough that swapping in ``AsyncAnthropic`` is a
drop-in change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import BaseModel, Field

from argus.investigate.agent import InvestigationAgent
from argus.investigate.context import truncate_tool_output
from argus.investigate.core_tools import register_core_tools
from argus.investigate.trajectory import StepKind, Trajectory, estimate_cost_usd
from argus.models import Incident, Severity
from argus.plugins import Hub, Tool

# ---------- Fake Anthropic client ----------


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
    def __init__(self, parent: FakeAnthropicClient):
        self._parent = parent

    async def create(self, **kwargs: Any) -> _FakeResponse:
        # Snapshot the messages list — the agent mutates its reference between
        # calls, so without this each stored call would end up pointing at the
        # final list state and tests couldn't inspect per-call history.
        captured = dict(kwargs)
        if "messages" in captured:
            captured["messages"] = list(captured["messages"])
        self._parent.calls.append(captured)
        if not self._parent.scripted_responses:
            raise AssertionError("FakeAnthropicClient ran out of scripted responses")
        return self._parent.scripted_responses.pop(0)


class FakeAnthropicClient:
    """Minimal stand-in for ``anthropic.AsyncAnthropic``."""

    def __init__(self, responses: list[_FakeResponse]):
        self.scripted_responses: list[_FakeResponse] = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.messages = _FakeMessages(self)


# ---------- Fixtures ----------


@pytest.fixture
def sample_incident() -> Incident:
    return Incident(
        id="abc123",
        check_name="saboten-api-job_health",
        service="saboten-api",
        severity=Severity.CRITICAL,
        message="NCOA: 17 failed jobs in 24h (critical threshold: 15)",
        details={"NCOA_failed_24h": 17, "DHC_failed_24h": 2},
        environment="prd",
        created_at=datetime(2026, 11, 2, 14, 30, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def empty_hub() -> Hub:
    """A hub with no tools, for testing agent behavior with zero tools."""
    return Hub()


# ---------- Tool abstraction ----------


class _EchoArgs(BaseModel):
    message: str = Field(description="echo back")


async def _echo_impl(args: _EchoArgs) -> dict[str, Any]:
    return {"echoed": args.message}


class TestToolAbstraction:
    def test_to_claude_tool_has_name_description_and_schema(self):
        tool = Tool(name="echo", description="d", args_model=_EchoArgs, impl=_echo_impl)
        shape = tool.to_claude_tool()
        assert shape["name"] == "echo"
        assert shape["description"] == "d"
        assert shape["input_schema"]["type"] == "object"
        assert "message" in shape["input_schema"]["properties"]

    async def test_call_validates_and_invokes(self):
        tool = Tool(name="echo", description="d", args_model=_EchoArgs, impl=_echo_impl)
        result = await tool.call({"message": "hi"})
        assert result == {"echoed": "hi"}

    async def test_call_raises_on_bad_args(self):
        from pydantic import ValidationError

        tool = Tool(name="echo", description="d", args_model=_EchoArgs, impl=_echo_impl)
        with pytest.raises(ValidationError):
            await tool.call({"message": 123, "extra": "nope"})

    def test_hub_rejects_duplicate_tool(self):
        tool = Tool(name="echo", description="d", args_model=_EchoArgs, impl=_echo_impl)
        hub = Hub()
        hub.register_tool(tool)
        with pytest.raises(ValueError, match="already registered"):
            hub.register_tool(tool)


# ---------- Context management ----------


class TestContext:
    def test_truncate_under_limit_is_passthrough(self):
        assert truncate_tool_output("hello", max_chars=100) == "hello"

    def test_truncate_over_limit_appends_marker(self):
        text = "x" * 500
        result = truncate_tool_output(text, max_chars=100)
        assert result.startswith("x" * 100)
        assert "truncated" in result
        assert "400 chars dropped" in result


# ---------- Trajectory + cost ----------


class TestTrajectory:
    def test_cost_estimate_for_known_model(self):
        cost = estimate_cost_usd("claude-opus-5-5", input_tokens=1_000_000, output_tokens=0)
        assert cost == pytest.approx(4.00)
        cost2 = estimate_cost_usd("claude-sonnet-5-5", input_tokens=0, output_tokens=1_000_000)
        assert cost2 == pytest.approx(10.00)

    def test_cost_estimate_for_unknown_model_is_zero(self):
        assert estimate_cost_usd("mystery-model", 100, 100) == 0.0

    def test_trajectory_round_trips_through_json(self, sample_incident):
        traj = Trajectory(incident_id=sample_incident.id, model="claude-opus-5-5")
        payload = traj.model_dump_json()
        reloaded = Trajectory.model_validate_json(payload)
        assert reloaded.incident_id == sample_incident.id
        assert reloaded.model == "claude-opus-5-5"


# ---------- Agent loop (the main thing) ----------


class TestAgentLoop:
    async def test_single_turn_end_turn_produces_report(
        self, empty_hub: Hub, sample_incident: Incident
    ):
        fake = FakeAnthropicClient(
            responses=[
                _FakeResponse(
                    content=[_FakeTextBlock("# Report\n\nAll fine.")],
                    stop_reason="end_turn",
                )
            ]
        )
        agent = InvestigationAgent(empty_hub, client=fake)
        report = await agent.investigate(sample_incident)
        assert report.status == "completed"
        assert "# Report" in report.markdown
        assert report.trajectory.tool_call_count == 0
        assert len(fake.calls) == 1

    async def test_tool_use_loop_executes_tool_and_feeds_result_back(
        self, sample_incident: Incident
    ):
        hub = Hub()
        hub.register_tool(
            Tool(
                name="echo",
                description="d",
                args_model=_EchoArgs,
                impl=_echo_impl,
            )
        )
        fake = FakeAnthropicClient(
            responses=[
                _FakeResponse(
                    content=[
                        _FakeTextBlock("Let me check."),
                        _FakeToolUseBlock(id="tool_1", name="echo", input={"message": "hi"}),
                    ],
                    stop_reason="tool_use",
                ),
                _FakeResponse(
                    content=[_FakeTextBlock("# Report\n\nEcho worked.")],
                    stop_reason="end_turn",
                ),
            ]
        )
        agent = InvestigationAgent(hub, client=fake)
        report = await agent.investigate(sample_incident)
        assert report.status == "completed"
        assert report.trajectory.tool_call_count == 1
        # The last message passed to the second call must be the tool_result
        # user turn built from the first assistant response.
        second_call_messages = fake.calls[1]["messages"]
        last = second_call_messages[-1]
        assert last["role"] == "user"
        assert isinstance(last["content"], list)
        assert any(b.get("type") == "tool_result" for b in last["content"])

    async def test_parallel_tool_use_in_one_turn(self, sample_incident: Incident):
        hub = Hub()
        hub.register_tool(Tool(name="echo", description="d", args_model=_EchoArgs, impl=_echo_impl))
        fake = FakeAnthropicClient(
            responses=[
                _FakeResponse(
                    content=[
                        _FakeToolUseBlock(id="t1", name="echo", input={"message": "a"}),
                        _FakeToolUseBlock(id="t2", name="echo", input={"message": "b"}),
                    ],
                    stop_reason="tool_use",
                ),
                _FakeResponse(
                    content=[_FakeTextBlock("# Done")],
                    stop_reason="end_turn",
                ),
            ]
        )
        agent = InvestigationAgent(hub, client=fake)
        report = await agent.investigate(sample_incident)
        assert report.trajectory.tool_call_count == 2
        # Both tool_results must be in a single user message, not split.
        tool_result_message = fake.calls[1]["messages"][-1]
        assert tool_result_message["role"] == "user"
        assert len(tool_result_message["content"]) == 2

    async def test_tool_raising_is_captured_as_error_result(self, sample_incident: Incident):
        async def _boom(_args: _EchoArgs) -> Any:
            raise RuntimeError("vendor API down")

        hub = Hub()
        hub.register_tool(Tool(name="echo", description="d", args_model=_EchoArgs, impl=_boom))
        fake = FakeAnthropicClient(
            responses=[
                _FakeResponse(
                    content=[_FakeToolUseBlock(id="t1", name="echo", input={"message": "x"})],
                    stop_reason="tool_use",
                ),
                _FakeResponse(
                    content=[_FakeTextBlock("# Report")],
                    stop_reason="end_turn",
                ),
            ]
        )
        agent = InvestigationAgent(hub, client=fake)
        report = await agent.investigate(sample_incident)
        tool_result_step = [s for s in report.trajectory.steps if s.kind == StepKind.TOOL_RESULT][0]
        assert tool_result_step.is_error is True
        assert "RuntimeError" in tool_result_step.content
        assert "vendor API down" in tool_result_step.content

    async def test_unknown_tool_name_is_captured_as_error(
        self, empty_hub: Hub, sample_incident: Incident
    ):
        fake = FakeAnthropicClient(
            responses=[
                _FakeResponse(
                    content=[_FakeToolUseBlock(id="t1", name="nope", input={})],
                    stop_reason="tool_use",
                ),
                _FakeResponse(
                    content=[_FakeTextBlock("# Report")],
                    stop_reason="end_turn",
                ),
            ]
        )
        agent = InvestigationAgent(empty_hub, client=fake)
        report = await agent.investigate(sample_incident)
        tool_result = [s for s in report.trajectory.steps if s.kind == StepKind.TOOL_RESULT][0]
        assert tool_result.is_error is True
        assert "not registered" in tool_result.content

    async def test_max_steps_stops_the_loop(self, sample_incident: Incident):
        hub = Hub()
        hub.register_tool(Tool(name="echo", description="d", args_model=_EchoArgs, impl=_echo_impl))
        # Agent asks for tool, over and over.
        tool_turn = _FakeResponse(
            content=[_FakeToolUseBlock(id="t", name="echo", input={"message": "x"})],
            stop_reason="tool_use",
        )
        fake = FakeAnthropicClient(responses=[tool_turn] * 10)
        agent = InvestigationAgent(hub, client=fake, max_steps=3)
        report = await agent.investigate(sample_incident)
        assert report.status == "stopped_at_limit"
        assert len(fake.calls) == 3

    async def test_token_counts_accumulate_across_turns(
        self, empty_hub: Hub, sample_incident: Incident
    ):
        fake = FakeAnthropicClient(
            responses=[
                _FakeResponse(
                    content=[_FakeTextBlock("# r")],
                    stop_reason="end_turn",
                    usage=_FakeUsage(input_tokens=123, output_tokens=45),
                )
            ]
        )
        agent = InvestigationAgent(empty_hub, client=fake)
        report = await agent.investigate(sample_incident)
        assert report.trajectory.total_input_tokens == 123
        assert report.trajectory.total_output_tokens == 45
        assert report.trajectory.estimated_cost_usd > 0

    async def test_long_tool_output_is_truncated(self, sample_incident: Incident):
        huge = "y" * 100_000

        async def _impl(_args: _EchoArgs) -> str:
            return huge

        hub = Hub()
        hub.register_tool(Tool(name="echo", description="d", args_model=_EchoArgs, impl=_impl))
        fake = FakeAnthropicClient(
            responses=[
                _FakeResponse(
                    content=[_FakeToolUseBlock(id="t", name="echo", input={"message": "x"})],
                    stop_reason="tool_use",
                ),
                _FakeResponse(
                    content=[_FakeTextBlock("# Report")],
                    stop_reason="end_turn",
                ),
            ]
        )
        agent = InvestigationAgent(hub, client=fake, max_tool_output_chars=1_000)
        await agent.investigate(sample_incident)
        tool_result_block = fake.calls[1]["messages"][-1]["content"][0]
        assert tool_result_block["type"] == "tool_result"
        assert len(tool_result_block["content"]) < 2_000
        assert "truncated" in tool_result_block["content"]

    async def test_system_prompt_is_sent_with_cache_control(
        self, empty_hub: Hub, sample_incident: Incident
    ):
        fake = FakeAnthropicClient(
            responses=[_FakeResponse(content=[_FakeTextBlock("# r")], stop_reason="end_turn")]
        )
        agent = InvestigationAgent(empty_hub, client=fake)
        await agent.investigate(sample_incident)
        system = fake.calls[0]["system"]
        assert isinstance(system, list)
        assert system[0]["cache_control"] == {"type": "ephemeral"}


# ---------- Core tools register cleanly ----------


class TestCoreToolRegistration:
    def test_register_core_tools_installs_expected_set(self):
        hub = Hub()
        register_core_tools(hub)
        names = set(hub.tools())
        assert {
            "get_incident_context",
            "query_splunk",
            "get_recent_deploys",
            "search_github_prs",
        } <= names

    async def test_stub_tools_return_configured_false(self, monkeypatch):
        monkeypatch.delenv("ARGUS_SPLUNK_BASE_URL", raising=False)
        monkeypatch.delenv("ARGUS_SPLUNK_TOKEN", raising=False)
        monkeypatch.delenv("ARGUS_GITHUB_TOKEN", raising=False)
        hub = Hub()
        register_core_tools(hub)
        for name in ("query_splunk", "get_recent_deploys", "search_github_prs"):
            tool = hub.tools()[name]
            raw_input = (
                {"query": "search *"}
                if name == "query_splunk"
                else {"service": "svc"}
                if name == "get_recent_deploys"
                else {"repo": "o/r"}
            )
            result = await tool.call(raw_input)
            assert result["configured"] is False
