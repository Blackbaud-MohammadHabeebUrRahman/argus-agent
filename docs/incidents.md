# Incidents in Argus

An incident is a durable record that something is wrong. Checks fire
continuously; an incident is the thing that gets alerted on, remembered,
investigated, and resolved.

## State machine

```
                    first non-OK check result
                              │
                              ▼
                      ┌──────────────┐
          OK result   │     OPEN     │  severity escalates
          ───────────▶│              │◀────────────────
                      └──────┬───────┘
                             │ operator acknowledges
                             ▼
                      ┌──────────────┐
                      │ ACKNOWLEDGED │
                      └──────┬───────┘
                             │ agent begins investigating
                             ▼
                      ┌──────────────┐
                      │ INVESTIGATING│
                      └──────┬───────┘
                             │ OK result from same check
                             ▼
                      ┌──────────────┐
                      │   RESOLVED   │  (TTL out of the active store)
                      └──────────────┘
```

Argus today drives OPEN → RESOLVED directly from check results.
ACKNOWLEDGED and INVESTIGATING become meaningful once Phase 2 (the
agent) and Phase 5 (HITL remediation) land.

## How a result becomes an incident

Every check result carries `(check_name, service, environment,
status, severity, message, details)`. The *dedup key* is
`check_name:service:environment` — the identity of the incident.

- **First non-OK result for a key.** `IncidentStore.create_or_update`
  creates a new `Incident` (`is_new=True`), `argus_incidents_opened_total`
  increments.
- **Subsequent non-OK results for the same key.** The incident is
  updated in place: timestamps advance, message/severity/details refresh,
  the last 10 check results are kept, `alert_count` increments.
- **An OK result for a key with an active incident.**
  `IncidentStore.resolve` deletes it, `argus_incidents_resolved_total`
  increments, the dedup cooldown is cleared.

## When Argus actually alerts

Alert dispatch is gated by `AlertDedup`. For each incident update:

1. Look up the stored cooldown for the dedup key.
2. If no cooldown → **alert**. Record the triggering severity, start a
   TTL equal to `alerting.dedup.cooldown_minutes`.
3. If cooldown exists AND the new severity is strictly greater than the
   stored one (warning → critical, critical → fatal) → **alert
   anyway**, overwrite the stored severity, restart the TTL. This is
   the *escalation re-alert* behavior.
4. Otherwise → suppress. The incident is still updated; the operator
   just doesn't get paged again.

Resolution clears the cooldown, so the next failure after a resolved
window alerts immediately rather than being swallowed by a stale TTL.

## What this means for operators

- A flapping check (OK → CRITICAL → OK → CRITICAL …) alerts once per
  cooldown window, not once per cycle.
- A slowly degrading service (WARNING → CRITICAL) pages twice: once on
  the first warning, once on escalation to critical. That's the point.
- A check that recovers for one interval and then fails again inside
  the cooldown window will NOT re-alert — because the cooldown was
  cleared on the OK, the next failure is treated as fresh.

## Metrics

The `/metrics` endpoint exposes:

- `argus_incidents_opened_total{service, severity}`
- `argus_incidents_resolved_total{service}`
- `argus_alerts_sent_total{channel}` — how often each channel fired
- `argus_checks_total{service, check, status}` — per-check outcome counts
- `argus_check_duration_seconds{service, check}` — latency histogram

Divide `incidents_opened_total` by `alerts_sent_total` to spot a
broken channel (incidents without pages). Divide `checks_total{status="critical"}`
by `checks_total` for a per-check failure rate.

## What's not here yet

- No ACKNOWLEDGED state transition (needs the alert channel to pass
  acks back — a Teams webhook can't; Teams Workflows can).
- No INVESTIGATING state (needs the Phase 2 investigation agent).
- No flapping dampening ("require N consecutive failures before
  opening"). Can be added via a rolling-state wrapper around the
  check if needed.
- No manual close from an operator (needs the MCP server, Phase 3).
