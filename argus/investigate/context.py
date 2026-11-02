"""Context management: keep tool outputs from blowing the context window.

A single verbose tool call (large log dump, big list of PRs) can take tens
of thousands of tokens. Instead of summarizing with another model call —
which is slow, costs tokens, and loses detail — we truncate large outputs
at a character budget and tell the agent what we dropped. The agent can
re-call the tool with a tighter query if it needs the rest.
"""

from __future__ import annotations

DEFAULT_MAX_TOOL_OUTPUT_CHARS = 20_000


def truncate_tool_output(output: str, max_chars: int = DEFAULT_MAX_TOOL_OUTPUT_CHARS) -> str:
    """Clip an oversized tool output and tell the model what was dropped."""
    if len(output) <= max_chars:
        return output
    kept = output[:max_chars]
    dropped = len(output) - max_chars
    return (
        kept + f"\n\n[truncated: {dropped} chars dropped. Re-call this tool with a tighter "
        f"query — a narrower time range or a more specific filter — to see the rest.]"
    )
