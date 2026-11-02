"""The investigation agent.

Takes an incident, loops ``user -> tool_use -> tool_result -> ...`` with
Claude, and returns a markdown report plus the full trajectory. Built
directly on the Anthropic Messages API's native tool_use mechanism
rather than wrapping ``client.beta.messages.tool_runner`` or the
Claude Agent SDK — the explicit loop gives us trajectory capture,
deterministic replay for evals, and testability with a mocked client.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from argus.models import Incident
from argus.telemetry import get_tracer

from .context import DEFAULT_MAX_TOOL_OUTPUT_CHARS, truncate_tool_output
from .prompts import SYSTEM_PROMPT, build_initial_user_message
from .trajectory import InvestigationReport, StepKind, Trajectory, TrajectoryStep

if TYPE_CHECKING:
    from argus.plugins import Hub, Tool

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_MAX_STEPS = 20
DEFAULT_MAX_TOKENS = 16_000


class InvestigationAgent:
    """Drives one investigation per incident.

    One agent can serve many investigations; it is cheap to construct
    and holds no per-incident state.
    """

    def __init__(
        self,
        hub: Hub,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_tool_output_chars: int = DEFAULT_MAX_TOOL_OUTPUT_CHARS,
        client: Any = None,
    ):
        self._hub = hub
        self._model = model
        self._max_steps = max_steps
        self._max_tokens = max_tokens
        self._max_tool_output_chars = max_tool_output_chars
        if client is not None:
            self._client = client
        else:
            self._client = _build_client(api_key)

    async def investigate(self, incident: Incident) -> InvestigationReport:
        tools_by_name = self._hub.tools()
        claude_tools = [t.to_claude_tool() for t in tools_by_name.values()]

        trajectory = Trajectory(incident_id=incident.id, model=self._model)
        initial_message = build_initial_user_message(incident)
        trajectory.steps.append(TrajectoryStep(kind=StepKind.USER, content=initial_message))
        messages: list[dict[str, Any]] = [{"role": "user", "content": initial_message}]

        with tracer.start_as_current_span("argus.investigate") as root_span:  # type: ignore[attr-defined]
            _set_attr(root_span, "argus.incident_id", incident.id)
            _set_attr(root_span, "argus.service", incident.service)
            _set_attr(root_span, "argus.model", self._model)

            final_markdown = ""
            stop_reason = "unknown"
            hit_step_limit = False
            for step_index in range(self._max_steps):
                response = await self._model_call(messages, claude_tools, trajectory)
                stop_reason = getattr(response, "stop_reason", "unknown") or "unknown"
                assistant_content = _as_content_list(response)
                trajectory.steps.append(
                    TrajectoryStep(
                        kind=StepKind.ASSISTANT,
                        content=_serialize_content(assistant_content),
                    )
                )
                messages.append({"role": "assistant", "content": assistant_content})

                tool_uses = [
                    block for block in assistant_content if _block_type(block) == "tool_use"
                ]
                final_markdown = _extract_text(assistant_content)

                if stop_reason != "tool_use" or not tool_uses:
                    break

                tool_results = await asyncio.gather(
                    *[self._run_tool(block, tools_by_name, trajectory) for block in tool_uses]
                )
                messages.append({"role": "user", "content": tool_results})

                if step_index == self._max_steps - 1:
                    hit_step_limit = True
                    logger.warning(
                        "Investigation %s hit max_steps=%d",
                        incident.id,
                        self._max_steps,
                    )

            trajectory.ended_at = datetime.now(timezone.utc)
            trajectory.stop_reason = "max_steps" if hit_step_limit else stop_reason

            status: str
            if hit_step_limit:
                status = "stopped_at_limit"
            elif stop_reason == "end_turn" and final_markdown:
                status = "completed"
            elif not final_markdown:
                status = "empty"
            else:
                status = "completed"

            _set_attr(root_span, "argus.stop_reason", stop_reason)
            _set_attr(root_span, "argus.tool_calls", trajectory.tool_call_count)
            _set_attr(root_span, "argus.input_tokens", trajectory.total_input_tokens)
            _set_attr(root_span, "argus.output_tokens", trajectory.total_output_tokens)
            _set_attr(root_span, "argus.cost_usd", trajectory.estimated_cost_usd)

        return InvestigationReport(
            incident_id=incident.id,
            service=incident.service,
            status=status,  # type: ignore[arg-type]
            markdown=final_markdown or "(agent returned no text)",
            trajectory=trajectory,
        )

    async def _model_call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        trajectory: Trajectory,
    ) -> Any:
        start = time.monotonic()
        with tracer.start_as_current_span("argus.model_call") as span:  # type: ignore[attr-defined]
            _set_attr(span, "argus.model", self._model)
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=tools,
                messages=messages,
            )
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
            output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
            trajectory.total_input_tokens += input_tokens
            trajectory.total_output_tokens += output_tokens
            _set_attr(span, "argus.input_tokens", input_tokens)
            _set_attr(span, "argus.output_tokens", output_tokens)
            _set_attr(span, "argus.duration_ms", (time.monotonic() - start) * 1000)
            return response

    async def _run_tool(
        self,
        tool_use_block: Any,
        tools_by_name: dict[str, Tool],
        trajectory: Trajectory,
    ) -> dict[str, Any]:
        name = _block_attr(tool_use_block, "name")
        tool_use_id = _block_attr(tool_use_block, "id")
        raw_input = _block_attr(tool_use_block, "input") or {}

        trajectory.steps.append(
            TrajectoryStep(
                kind=StepKind.TOOL_USE,
                content=raw_input,
                tool_name=name,
                tool_use_id=tool_use_id,
            )
        )

        tool = tools_by_name.get(name)
        start = time.monotonic()
        is_error = False
        with tracer.start_as_current_span("argus.tool_call") as span:  # type: ignore[attr-defined]
            _set_attr(span, "argus.tool", name or "")
            if tool is None:
                output_text = f"error: tool {name!r} is not registered"
                is_error = True
            else:
                try:
                    result = await tool.call(raw_input)
                    output_text = _format_tool_output(result)
                except Exception as exc:
                    logger.exception("tool %s raised", name)
                    output_text = f"error: {type(exc).__name__}: {exc}"
                    is_error = True
            output_text = truncate_tool_output(output_text, self._max_tool_output_chars)
            duration_ms = (time.monotonic() - start) * 1000
            _set_attr(span, "argus.duration_ms", duration_ms)
            _set_attr(span, "argus.is_error", is_error)

        trajectory.steps.append(
            TrajectoryStep(
                kind=StepKind.TOOL_RESULT,
                content=output_text,
                tool_name=name,
                tool_use_id=tool_use_id,
                duration_ms=duration_ms,
                is_error=is_error,
            )
        )
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": output_text,
            "is_error": is_error,
        }


def _build_client(api_key: str | None) -> Any:
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:
        raise RuntimeError(
            "The 'anthropic' package is required for investigations. "
            "Install it with: pip install -e '.[ai]'"
        ) from exc
    return AsyncAnthropic(api_key=api_key) if api_key else AsyncAnthropic()


def _as_content_list(response: Any) -> list[Any]:
    content = getattr(response, "content", None)
    return list(content) if content else []


def _block_type(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get("type", ""))
    return str(getattr(block, "type", ""))


def _block_attr(block: Any, name: str) -> Any:
    if isinstance(block, dict):
        return block.get(name)
    return getattr(block, name, None)


def _extract_text(blocks: list[Any]) -> str:
    parts: list[str] = []
    for block in blocks:
        if _block_type(block) == "text":
            text = _block_attr(block, "text") or ""
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _serialize_content(blocks: list[Any]) -> list[dict[str, Any]]:
    """Reduce content blocks (dicts or Anthropic model objects) to plain dicts."""
    out: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, dict):
            out.append(block)
        elif hasattr(block, "model_dump"):
            out.append(block.model_dump())
        else:
            out.append(
                {
                    "type": _block_type(block),
                    "text": _block_attr(block, "text"),
                    "name": _block_attr(block, "name"),
                    "input": _block_attr(block, "input"),
                    "id": _block_attr(block, "id"),
                }
            )
    return out


def _format_tool_output(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, default=str, indent=2)
    except TypeError:
        return str(result)


def _set_attr(span: Any, name: str, value: Any) -> None:
    setter = getattr(span, "set_attribute", None)
    if setter:
        with contextlib.suppress(Exception):
            setter(name, value)
