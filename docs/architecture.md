# Architecture

A longer-form companion to the diagram in the README. One paragraph per
major boundary.

## Core vs plugins

The `argus/` package is **product-agnostic**: engine, scheduler,
incident store, alert router, investigation agent, MCP server, eval
harness, security primitives. Nothing in it knows Saboten exists.

Product-specific pieces live under `products/<name>/` and are
discovered through Python entry points. Each plugin exposes a single
`register(hub)` function that calls `hub.register_check`,
`hub.register_tool`, and `hub.register_action` to install its
contributions. The in-repo plugins are `saboten` (the first
production target) and `example` (a template that proves the core is
decoupled).

The seam is the [`Hub`](../argus/plugins.py) — a plain registry
object. Everything the agent, the engine, and the MCP server need
goes through it. Swap plugins, swap behavior. Nothing else moves.

## The monitoring loop

[`scheduler.py`](../argus/core/scheduler.py) uses APScheduler to run
each registered check at its own interval. Checks return a
`CheckResult` (`argus/models.py`); the engine inspects the result and
either resolves an active incident (OK result) or creates/updates one
(non-OK). Dedup (`argus/alert/dedup.py`) decides whether to actually
alert — a plain cooldown would silence a warning→critical escalation,
so dedup stores the severity alongside the TTL and lets a strictly
higher severity bypass the cooldown.

The engine instruments every check and every dispatch with
Prometheus counters and OpenTelemetry spans, so operators can SLO
the agent itself.

## The investigation agent

[`argus/investigate/agent.py`](../argus/investigate/agent.py) wraps
the Anthropic Messages API's native tool-use mechanism directly
rather than hiding behind `claude-agent-sdk` or
`client.beta.messages.tool_runner`. The explicit loop is longer code
but gives us three things the wrappers don't:

1. **Trajectory capture.** Every step (user turn, assistant turn,
   tool call, tool result) lands in a serializable `Trajectory`
   model. Phase 4 evals replay these; a post-incident review reads
   them.
2. **Deterministic replay for tests.** A `FakeAnthropicClient`
   scripts responses, so the full control flow is exercised in CI
   without any network calls or token spend.
3. **Full control over context management.** Oversized tool outputs
   get truncated with a `[truncated: ... re-call with a tighter
   query]` marker so the agent knows to narrow its filter; a
   max-steps safety net prevents runaway loops.

The system prompt
([`argus/investigate/prompts.py`](../argus/investigate/prompts.py))
is cached via `cache_control: ephemeral`, so running N
investigations in a window pays for it once.

## The eval harness

[`evals/`](../evals/) treats "did the agent do the right thing"
as a measurable property. Scenarios are hand-written YAML with the
incident, mock tool responses (optional per-arg matchers), expected
behavior (keywords per section of the report, required/forbidden
tools, judge criteria), and budgets. The grader has two layers:
deterministic checks catch budget / tool / keyword regressions
precisely, and a Haiku-as-judge grades the narrative against the
scenario's `judge_criteria` with a structured verdict
(`match`/`partial`/`miss`).

`make evals` fans scenarios × models through a concurrency semaphore
and emits a per-run report (Markdown for stdout, HTML with
expandable detail blocks for `evals/results/<ts>/report.html`, JSON
for diffing between runs).

## Remediation

[`argus/remediate/`](../argus/remediate/) is the "the agent
proposes, a human disposes" layer. The investigation agent can call
hub-registered `Action`s with validated args and a reasoning string.
The engine consults an
[`EnvironmentPolicy`](../argus/remediate/policy.py) — dev
auto-approves non-destructive, prd always holds for a human — and
either executes or writes a pending proposal. Approvers come through
whatever channel exposes `approve_and_execute`: today a CLI, soon a
Teams-workflow callback, eventually MCP from Claude Code.

Every state transition writes a line to the
[`AuditLog`](../argus/remediate/audit.py) in JSONL, so a quarterly
incident review has the ground-truth record of what the agent
proposed, who approved it, and what the action returned.

## MCP server

[`argus/mcp/server.py`](../argus/mcp/server.py) exposes Argus to any
MCP client — Claude Code, Claude Desktop, Cursor — so operators can
drive investigations from their chat without SSHing anywhere. The
handlers are decoupled from the official SDK transport, so they're
unit-testable without stdio or JSON-RPC plumbing; `run_stdio` is a
few dozen lines of wiring at the end.

## Security

[`SECURITY.md`](../SECURITY.md) walks the full threat model. The
TL;DR:
- Prompt-injection attempts in log content are neutered before the
  agent sees them.
- The destructive remediation path never auto-fires in production.
- PII and secret-shaped tokens are redacted before any alert leaves
  the perimeter.
- Plugins are explicit via entry points — nothing loads from the
  filesystem on its own.

## Deployment

One Fargate service, one ElastiCache cluster, four Secrets Manager
secrets, two IAM roles (execution + task, least-privilege). Full
walkthrough in
[docs/deployment-aws.md](deployment-aws.md). Rough-cut
cost: ~$100/mo for a staging stack, Anthropic tokens on top of that.
