# Saboten Sentinel — Roadmap

AI-powered monitoring, investigation, and remediation agent for the Saboten
platform. The project doubles as a career-growth vehicle: shipping it covers
agentic AI engineering, cloud, system design, security, and business framing in
one artifact.

## How this project maps to the growth priorities

| Priority | What delivers it here |
|---|---|
| 1. AI engineering beyond prompting | `investigate/` as an Agent-SDK agent, `mcp/` as an MCP server, an eval harness, cost/latency telemetry |
| 2. One cloud, properly | Deploy to AWS (ECS Fargate + ElastiCache + Secrets Manager) with Terraform |
| 3. System design & reliability | Dedup, idempotency, incident state machine, OpenTelemetry, blue/green deploy |
| 4. Security | Threat model for prompt injection via log content, least-privilege tool scopes, HITL approval for remediation |
| 5. Business framing | Case-study README with MTTR / token-cost / eval-accuracy metrics |

## Sequencing

Phases run in this order: 0 → 1 → 2 → 4 → 3 → 5 → 6 → 7 → 8.
Evals (4) go before MCP (3): once the agent exists, locking its behaviour down
with evals is more valuable than exposing it over a protocol you can bolt on
later.

---

## Phase 0 — Foundation hygiene

- `git init`, push to GitHub as a public repo
- GitHub Actions: ruff + mypy + pytest on every PR
- `tests/conftest.py` plus smoke tests for `config.load_config` and the engine lifecycle
- Structured JSON logging + OpenTelemetry bootstrap (console exporter)
- Pin Python version; `Makefile` with `dev`, `test`, `lint`, `run-local`

**Deliverable:** green CI badge, one-command local run.

## Phase 1 — Make the monitoring loop solid

- Finish the three monitors; add a Prometheus `/metrics` endpoint
- Testcontainers-based integration tests: real Redis, fake Saboten SOAP endpoint
- Document the incident state machine (open → acknowledged → investigating → resolved) in `docs/incidents.md`
- Dedup edge-case tests (TTL expiry, severity escalation re-opens, flapping)

**Deliverable:** `docker compose up` yields a monitor that detects a seeded failure and posts to a Teams/Slack test channel.

## Phase 2 — The agentic investigation layer

The core AI story. Do not skip to shiny things before this works.

- `investigate/agent.py` built on the Claude Agent SDK (not raw `anthropic.messages.create`)
- Tools defined as pydantic schemas, implementations behind adapters so they can be mocked:
  - `query_splunk(query, time_range)`
  - `get_job_history(external_job_id)`
  - `check_vendor_api_health(vendor)`
  - `get_recent_deploys(service, hours)`
  - `search_github_prs(service, since)`
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

**Deliverable:** drive the sentinel from Claude Code via MCP.

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

- `remediate/actions.py` with a whitelisted action set: `restart_worker`, `requeue_job`, `flush_cache_key`
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

- README with: problem (SRE toil on an async pipeline), design, labelled diagram, metrics table from Phase 4, demo GIF
- 2-minute Loom walkthrough linked at the top
- One blog post or tech-talk: "Agentic SRE assistant with Claude + MCP"
- Resume bullet: "Designed and shipped an agentic monitoring/remediation system (Claude Agent SDK, MCP, OTel, AWS/Terraform) with an eval harness that keeps regression under X%."

## On the Claude Developer certification

Treat it as the milestone that forces Phases 2–4 to finish. The Developer
syllabus is essentially those phases. Don't buy prep material until Phase 2
ships; by then the exam is a formality.
