"""Prometheus metrics + a tiny HTTP exposition server.

Argus exposes four signals that are useful on day one:

- ``argus_checks_total{service,check,status}``  — how often each check
  ran and what it concluded. Divide critical by total for a per-check
  failure rate.
- ``argus_check_duration_seconds{service,check}`` — latency histogram.
  Spiking latency often precedes an outage.
- ``argus_incidents_opened_total{service,severity}`` and
  ``argus_incidents_resolved_total{service}`` — flow of incidents in
  and out of the active set; the difference is "currently active."
- ``argus_alerts_sent_total{channel}`` — how often each alert channel
  fired. Divergence from incidents_opened points at a channel outage.

The ``prometheus_client`` package is a soft dependency: if it isn't
installed, every metric is a silent no-op and ``start_metrics_server``
is a no-op too. This keeps metrics opt-in while every call site is
written as if they're on.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Histogram, start_http_server

    _ENABLED = True
except ImportError:  # pragma: no cover - exercised only when extra is missing
    _ENABLED = False

    class _NoOp:
        def labels(self, *_args: object, **_kwargs: object) -> _NoOp:
            return self

        def inc(self, *_args: object, **_kwargs: object) -> None:
            pass

        def observe(self, *_args: object, **_kwargs: object) -> None:
            pass

    Counter = Histogram = _NoOp  # type: ignore[assignment,misc]

    def start_http_server(*_args: object, **_kwargs: object) -> None:  # type: ignore[misc]
        pass


CHECKS_TOTAL = Counter(
    "argus_checks_total",
    "Total number of check executions",
    ["service", "check", "status"],
)

CHECK_DURATION = Histogram(
    "argus_check_duration_seconds",
    "Check execution duration in seconds",
    ["service", "check"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

INCIDENTS_OPENED = Counter(
    "argus_incidents_opened_total",
    "Incidents opened by Argus",
    ["service", "severity"],
)

INCIDENTS_RESOLVED = Counter(
    "argus_incidents_resolved_total",
    "Incidents resolved (check returned OK)",
    ["service"],
)

ALERTS_SENT = Counter(
    "argus_alerts_sent_total",
    "Alerts dispatched to a channel",
    ["channel"],
)


_server_started = False


def start_metrics_server(port: int, addr: str = "0.0.0.0") -> None:
    """Expose metrics over HTTP. Idempotent and safe to call without the extra."""
    global _server_started
    if _server_started:
        return
    if not _ENABLED:
        logger.info("prometheus_client not installed; metrics endpoint disabled")
        _server_started = True
        return
    start_http_server(port, addr=addr)
    logger.info("metrics server listening on %s:%d", addr, port)
    _server_started = True


def _reset_for_tests() -> None:
    """Only for tests — allows re-starting the server across cases."""
    global _server_started
    _server_started = False
