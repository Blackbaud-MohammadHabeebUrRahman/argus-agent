"""Build a Hub whose tools return scenario-defined mock responses.

The real Tool definitions on the production hub keep their names,
descriptions, and pydantic args schemas — only the ``impl`` is swapped
for a function that matches the agent's call against the scenario's
rule list and returns the matching response. That preserves the
model's view of each tool (same instructions, same schema) while
giving the harness full control over what the agent sees.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from argus.plugins import Hub, Tool, build_hub

if TYPE_CHECKING:
    from pydantic import BaseModel

    from .scenario import MockToolResponse, Scenario


def _args_match(call_args: dict[str, Any], rule_match: dict[str, Any]) -> bool:
    """A rule matches when every key in rule_match equals the call's value."""
    return all(call_args.get(k) == v for k, v in rule_match.items())


def _make_mock_impl(tool_name: str, rules: list[MockToolResponse]) -> Callable[[BaseModel], Any]:
    async def impl(args: BaseModel) -> Any:
        call_args = args.model_dump()
        for rule in rules:
            if _args_match(call_args, rule.args_match):
                return rule.response
        return {
            "error": (
                f"no mock response matched for tool {tool_name!r} with "
                f"args {call_args!r}. Add a MockToolResponse to the scenario."
            )
        }

    return impl


def build_mock_hub(scenario: Scenario) -> Hub:
    """Build a Hub that mirrors the production tool surface with mocked impls.

    All tools from the real hub are included so the agent sees the same
    choices it would in prod. Any tool not covered by the scenario's
    ``mock_tools`` returns a diagnostic error — forgetting to mock a
    tool is a test authoring bug, not something the agent should guess
    its way through.
    """
    real_hub = build_hub(enabled_products=scenario.products)
    mock_hub = Hub()
    # Copy the check registry so build_mock_hub can be used anywhere a Hub is.
    for type_name, factory in real_hub.check_factories().items():
        mock_hub.register_check(type_name, factory)
    for tool in real_hub.tools().values():
        rules = scenario.mock_responses_for(tool.name)
        mock_tool = Tool(
            name=tool.name,
            description=tool.description,
            args_model=tool.args_model,
            impl=_make_mock_impl(tool.name, rules),
        )
        mock_hub.register_tool(mock_tool)
    return mock_hub
