"""Smoke tests for the Prometheus metrics module."""

from __future__ import annotations

from argus import metrics


def test_counters_increment_without_error():
    metrics.CHECKS_TOTAL.labels(service="svc", check="chk", status="ok").inc()
    metrics.CHECK_DURATION.labels(service="svc", check="chk").observe(0.123)
    metrics.INCIDENTS_OPENED.labels(service="svc", severity="critical").inc()
    metrics.INCIDENTS_RESOLVED.labels(service="svc").inc()
    metrics.ALERTS_SENT.labels(channel="teams").inc()


def test_start_metrics_server_is_idempotent():
    metrics._reset_for_tests()
    # Port 0 lets the OS pick — avoids collisions on the test runner.
    metrics.start_metrics_server(port=0)
    metrics.start_metrics_server(port=0)  # second call is a no-op
    metrics._reset_for_tests()
