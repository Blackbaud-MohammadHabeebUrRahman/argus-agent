# Argus

**A pluggable, agentic SRE assistant.** Argus watches services it is
configured to care about, opens incidents when they misbehave, uses a
Claude agent with product-specific tools to investigate the root cause,
and proposes human-in-the-loop remediation. Everything is scored by an
eval harness so the agent is measured, not vibes-checked.

```
                                       argus/metrics (Prometheus)
                                                  ▲
            ┌─────────────────────────────────────┴─────────────────────────────┐
            │                                                                   │
┌───────────┴────────────┐    ┌──────────────────┐    ┌──────────────────────┐  │
│ monitor (http, tcp,    │───▶│ incident store   │───▶│ alert router         │──┼──▶ Teams
│ redis, prometheus_     │    │ (Redis +         │    │ (sev-aware, dedup +  │  │    Slack
│ scrape, plugin-added)  │    │ dedup w/ sev     │    │ severity escalation) │  │
└────────────────────────┘    │ escalation)      │    └──────────────────────┘  │
                              └────────┬─────────┘                              │
                                       │                                        │
                                       ▼                                        │
                              ┌──────────────────┐          ┌─────────────────┐ │
                              │ investigation    │─────────▶│ Claude agent    │ │
                              │ agent (Agent SDK │          │ (Opus / Sonnet /│ │
                              │ tool-use loop,   │          │ Haiku, OTel-    │ │
                              │ trajectory +     │◀─────────│ traced, cached  │ │
                              │ cost tracked)    │          │ system prompt)  │ │
                              └────────┬─────────┘          └─────────────────┘ │
                                       │                                        │
                                       ▼                                        │
                              ┌──────────────────┐                              │
                              │ remediation      │──▶ HITL approval             │
                              │ engine           │    (per-env policy)          │
                              └──────────────────┘                              │
                                                                                │
┌──────────────────────────────────────────────────────────────────────────────┐│
│  Hub ◀── products/saboten (checks, tools, remediations)                      ││
│       ◀── products/example (template)                                        ││
│       ◀── your-plugin (pip install, declare the entry point)                 ││
└──────────────────────────────────────────────────────────────────────────────┘│
                                                                                │
                                                                     MCP server ┘
                                                 (drive from Claude Code / Desktop)
```

## Why

Most monitoring tools stop at "something is wrong, you figure it out."
Argus wraps the LLM-based "figure it out" step as a real system:
versioned prompts, mockable tools, trajectory capture, replay, an eval
harness, and an audited HITL layer for the action it proposes to take.
It's the shape of an incident-response copilot that an SRE on a 3am
page can trust.

## Status

| Phase | What | Shipped |
|---|---|---|
| 0 | Foundation: CI, lint/format/test, JSON logging, OpenTelemetry bootstrap | ✓ |
| 0.5 | Plugin architecture: Hub, entry-point discovery, products/saboten as reference, products/example as template | ✓ |
| 1 | Monitoring loop: http/tcp/redis/prometheus_scrape checks, Prometheus /metrics endpoint, severity-escalation dedup, incident state doc | ✓ |
| 2 | Investigation agent: Claude Messages API with explicit tool-use loop, trajectory capture, context truncation, OTel spans, CLI, four core tools, two Saboten tools | ✓ |
| 3 | MCP server: resources + tools + prompts over the official SDK, Claude Code / Desktop integration | ✓ |
| 4 | Eval harness: scenario YAML, mock hub, deterministic + Haiku-judge grader, per-model sweep, HTML + Markdown reports | ✓ |
| 5 | HITL remediation: Action registry, per-env approval policy, in-memory store (Redis-swap one method), JSONL audit log, three Saboten actions | ✓ |
| 6 | AWS deployment: Terraform (VPC + ECS Fargate + ElastiCache + Secrets Manager + CloudWatch), multi-stage prod Dockerfile, OIDC CI deploy workflow | ✓ |
| 7 | Security: SECURITY.md threat model, prompt-injection sanitization at tool-output boundary, PII redaction before Teams/Slack, per-severity tool allowlist | ✓ |
| 8 | Packaging: this README, architecture diagram, docs set, resume pitch | ✓ |

## 60-second local setup

```bash
# One: install
git clone <this-repo> argus && cd argus && make dev

# Two: configure
cp .env.example .env
# add your ANTHROPIC_API_KEY

# Three: run
make test          # 144 unit tests, under 2 seconds
make evals-quick   # one scenario against Haiku, ~$0.01
```

Then open `evals/results/latest/report.html`.

## Plug in your product

```python
# products/myapp/__init__.py
from argus.plugins import Hub
from .checks import register_checks
from .tools import register_tools

def register(hub: Hub) -> None:
    register_checks(hub)
    register_tools(hub)
```

Register the entry point in `pyproject.toml`:

```toml
[project.entry-points."argus.plugins"]
myapp = "products.myapp:register"
```

Full walkthrough in [docs/writing-a-plugin.md](docs/writing-a-plugin.md).

## Doc map

- [ROADMAP.md](ROADMAP.md) — eight-phase plan, this is where context lives
- [SECURITY.md](SECURITY.md) — threat model and mitigations
- [docs/incidents.md](docs/incidents.md) — incident state machine, dedup/alert flow
- [docs/writing-a-plugin.md](docs/writing-a-plugin.md) — add a new product
- [docs/mcp.md](docs/mcp.md) — hook up Claude Code / Desktop
- [docs/deployment-aws.md](docs/deployment-aws.md) — Terraform / Fargate / Secrets Manager

## Development

```bash
make dev        # venv + install [dev,ai,mcp,otel,metrics,integration]
make test       # unit tests
make lint       # ruff check
make fmt        # ruff format + --fix
make typecheck  # mypy
make check      # all three
make evals      # live sweep across claude-opus-5-5, sonnet-5-5, haiku-5-5
make evals-quick  # haiku only, cheap iteration
```

## License

TBD.

---

> **Resume bullet** — *Designed and shipped Argus, a pluggable agentic
> monitoring, investigation, and remediation framework (Python,
> Claude Messages API with native tool-use, MCP, OpenTelemetry,
> Prometheus, Redis, AWS Fargate / Terraform). Ships with an eval
> harness (deterministic grader + Haiku-as-judge) that scores agent
> output per scenario per model and gates CI on pass rate. First
> production deployment: Blackbaud's Saboten data-enrichment
> pipeline, as a reference plugin.*
