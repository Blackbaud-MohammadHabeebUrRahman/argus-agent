"""Telemetry bootstrap smoke tests."""

from __future__ import annotations

from argus.telemetry import configure_tracing, get_tracer


def test_configure_tracing_is_safe_without_endpoint():
    # No OTEL_EXPORTER_OTLP_ENDPOINT set: should still succeed with console exporter
    configure_tracing(service_name="test-argus")


def test_get_tracer_returns_usable_span_context():
    configure_tracing(service_name="test-argus")
    tracer = get_tracer("test")
    with tracer.start_as_current_span("unit-span"):  # type: ignore[attr-defined]
        pass
