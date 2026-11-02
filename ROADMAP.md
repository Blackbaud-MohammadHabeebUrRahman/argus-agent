# Argus — Roadmap

Argus is a product-agnostic AI monitoring, investigation, and remediation
agent. The core framework ships with generic health checks, alert channels,
an agent harness, an MCP server, and an eval harness; per-product behaviour
(custom checks, investigation tools, remediations) is contributed through
plugins. Saboten ships as the first reference plugin and the project's own
dogfood target.

The project doubles as a career-growth vehicle: shipping it covers agentic AI
engineering, cloud, system design, security, and business framing in one
artifact.

## How this project maps to the growth priorities

| Priority | What delivers it here |
|---|---|
| 1. AI engineering beyond prompting | `investigate/` as an Agent-SDK agent, `mcp/` as an MCP server, an eval harness, cost/latency telemetry |
| 2. One cloud, properly | Deploy to AWS (ECS Fargate + ElastiCache + Secrets Manager) with Terraform |
| 3. System design & reliability | Dedup, idempotency, incident state machine, OpenTelemetry, blue/green deploy |
| 4. Security | Threat model for prompt injection via log content, least-privilege tool scopes, HITL approval for remediation |
| 5. Business framing | Case-study README with MTTR / token-cost / eval-accuracy metrics |

## Sequencing

Phases: 0 → 0.5 → 1 → 2 → 4 → 3 → 5 → 7 → 6 → 8. Evals (4) go before MCP (3):
once the agent exists, locking its behaviour down with evals matters more than
exposing it over a protocol you can bolt on later.

## Status

| Phase | What | Status |
|---|---|---|
| 0 | Foundation (CI, logging, OTel, pins) | ✅ shipped |
| 0.5 | Plugin architecture (Hub + entry points + products/) | ✅ shipped |
| 1 | Monitoring loop (http/tcp/redis/prom, Prometheus /metrics, dedup escalation, incident doc) | ✅ shipped |
| 2 | Investigation agent (Messages API tool-use loop, trajectory, OTel, CLI, 4 core + 2 Saboten tools) | ✅ shipped |
| 4 | Eval harness (scenarios, mock hub, deterministic + judge grader, HTML report) | ✅ shipped |
| 3 | MCP server (official SDK, resources + tools + prompts) | ✅ shipped |
| 5 | HITL remediation (Action registry, approval store, policy, audit, 3 Saboten actions) | ✅ shipped |
| 7 | Security pass (SECURITY.md, sanitize, PII strip, tool allowlist) | ✅ shipped |
| 6 | AWS deployment (Terraform, prod Dockerfile, OIDC CI) | ✅ shipped |
| 8 | Packaging (README, architecture doc, resume pitch) | ✅ shipped |

---

## Phase 0 — Foundation hygiene

- `git init`, push to GitHub as a public repo
- GitHub Actions: ruff + mypy + pytest on every PR
- `tests/conftest.py` plus smoke tests for `config.load_config` and the engine lifecycle
- Structured JSON logging + OpenTelemetry bootstrap (console exporter)
- Pin Python version; `Makefile` with `dev`, `test`, `lint`, `run-local`

**Deliverable:** green CI badge, one-command local run.

## Phase 0.5 — Plugin architecture (product-agnostic core)

Lift the Saboten-shaped assumptions out of the core so Argus is reusable.

- `argus/plugins.py`: `Hub` with `register_check`, `register_tool`,
  `register_remediation`, `register_config_schema`
- Refactor `argus/core/engine.py` to resolve check types from the registry
  instead of a hardcoded `CHECK_FACTORIES` dict
- `products/saboten/` as the first plugin:
  - `checks.py` — `SabotenJobHealth` check (the current `/monitor` endpoint)
  - `tools.py` — `get_saboten_job_state`, `requeue_saboten_job` (stubs for now)
  - `config/saboten.yaml` — moves out of `config/argus.yaml`
  - `__init__.py` — `register(hub)` entry point
- Entry points in `pyproject.toml` so `pip install argus-plugin-foo` auto-registers
- `docs/writing-a-plugin.md` walks through a minimal second plugin
- Config: top-level `product:` key selects which plugin ships product-specific bits

**Deliverable:** a second product plugin (even a toy one, e.g. a Postgres box) proves the core is decoupled.

## Phase 1 — Make the monitoring loop solid

- Finish the built-in generic monitors (http, redis, tcp, prometheus_scrape); add a Prometheus `/metrics` endpoint
- Testcontainers integration tests: real Redis, a fake HTTP target, and the Saboten plugin pointed at a mock SOAP endpoint
- Document the incident state machine (open → acknowledged → investigating → resolved) in `docs/incidents.md`
- Dedup edge-case tests (TTL expiry, severity escalation re-opens, flapping)

**Deliverable:** `docker compose up` yields a monitor that detects a seeded failure and posts to a Teams/Slack test channel.

## Phase 2 — The agentic investigation layer

The core AI story. Do not skip to shiny things before this works.

- `argus/investigate/agent.py` built on the Claude Agent SDK (not raw `anthropic.messages.create`)
- Core tools (every plugin inherits):
  - `query_splunk(query, time_range)`
  - `get_recent_deploys(service, hours)`
  - `search_github_prs(service, since)`
  - `get_cloudwatch_logs(group, filter, since)`
- Plugin-contributed tools: Saboten plugin registers `get_saboten_job_history`, `check_saboten_vendor_api_health`
- Tools defined as pydantic schemas with adapters behind them (mockable in tests)
- Context management: compress tool outputs above N tokens with a summarizer sub-call; cap trajectory length
- Trace every tool call and model call with OTel spans; log input/output tokens per investigation
- Replay: given an incident JSON, re-run offline — foundation for Phase 4

**Deliverable:** given a stuck-job incident, the agent produces a root-cause markdown report with cited evidence.

## Phase 3 — The MCP server

- `mcp/server.py` using the official `mcp` SDK
- Resources: `incident://open`, `service://{name}/status`, `alert://recent`
- Tools: `investigate_incident`, `query_logs`, `check_vendor_api`
- Prompts: templates for "stuck jobs", "worker crash loop", "vendor latency spike"
- Document how to add it to Claude Code and Claude Desktop

**Deliverable:** drive the argus from Claude Code via MCP.

## Phase 4 — Evals

The scarce skill. This is the interview story.

- Fixture library: 15–20 scenarios in `evals/fixtures/` — mock Splunk responses, job states, expected root cause + remediation
- Deterministic grader for structured fields; LLM-as-judge (Haiku) for the narrative
- Dimensions tracked: correctness, tool-call count, p95 latency, cost per investigation
- `pytest -m eval` fails CI if accuracy drops below a threshold
- A/B harness: swap Haiku ↔ Sonnet ↔ Opus; produce a comparison table
- Simple `evals/report.html` dashboard checked into the repo

**Deliverable:** `make evals` → table of pass-rate, cost, latency per model.

## Phase 5 — Remediation with human-in-the-loop

- Core action registry in `argus/remediate/`; plugins register whitelisted actions
- Saboten plugin ships: `restart_saboten_worker`, `requeue_saboten_job`, `flush_cache_key`
- Approval flow: agent proposes → Teams card with Approve/Reject → audit log → execute
- Per-environment scoping: dev auto-approves, stg/prd require human
- Every action emits an OTel span and a structured audit record

**Deliverable:** end-to-end: stuck job → investigated → remediation proposed → approved → requeued → verified.

## Phase 6 — Cloud deployment (AWS)

- Terraform for everything: VPC, ECS Fargate service, ElastiCache for Redis, Secrets Manager, CloudWatch Logs
- Split IAM roles: monitor can read; remediator can act, scoped per environment
- OTel collector sidecar → AWS X-Ray or Honeycomb free tier
- GitHub Actions deploys on tag; staging gates production

**Deliverable:** one `terraform apply` stands the whole thing up in a sandbox AWS account.

## Phase 7 — Security pass

- Threat model doc: prompt injection through log content, tool-chain privilege escalation, data exfiltration via alert channels
- Mitigations: sanitize at the Splunk adapter boundary, allow-list tools per severity, strip PII before posting to channels
- Red-team notebook: craft malicious log entries, verify the agent refuses or doesn't call unauthorized tools
- `SECURITY.md` — itself a resume artifact

## Phase 8 — Package it

- README pitching Argus as the framework (not a Saboten-specific tool): problem, pluggable design, labelled diagram, Saboten reference plugin case study with metrics from Phase 4, demo GIF
- `docs/writing-a-plugin.md` walkthrough with a second, non-Saboten plugin
- 2-minute Loom walkthrough linked at the top of the README
- One blog post or tech-talk: "Argus: an agentic SRE assistant you can point at anything"
- Publish `argus-agent` to PyPI (optional but a strong signal)
- Resume bullet: "Designed and shipped Argus, a pluggable agentic monitoring/investigation/remediation framework (Claude Agent SDK, MCP, OTel, AWS/Terraform) with an eval harness that keeps regression under X%. First production deployment: Blackbaud's Saboten pipeline."

## On the Claude Developer certification

Treat it as the milestone that forces Phases 2–4 to finish. The Developer
syllabus is essentially those phases. Don't buy prep material until Phase 2
ships; by then the exam is a formality.
