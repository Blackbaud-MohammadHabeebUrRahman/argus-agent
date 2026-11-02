"""OpenTelemetry bootstrap.

Called once at startup. If the ``otel`` extra isn't installed, this is a
no-op so the sentinel still runs in minimal environments. When installed
and ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, traces ship over OTLP; otherwise
they print to stdout, which is useful during local development.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("sentinel.telemetry")

_initialized = False


def configure_tracing(service_name: str = "saboten-sentinel") -> None:
    """Install a tracer provider. Idempotent."""
    global _initialized
    if _initialized:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
    except ImportError:
        logger.info("opentelemetry not installed; tracing disabled")
        _initialized = True
        return

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            logger.info("otel: exporting to %s", endpoint)
        except ImportError:
            logger.warning("otel OTLP exporter not available; falling back to console")
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _initialized = True


def get_tracer(name: str) -> object:
    """Return a tracer; a no-op one if OTel isn't installed."""
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        class _NoOpTracer:
            def start_as_current_span(self, *_args: object, **_kwargs: object) -> object:
                from contextlib import nullcontext
                return nullcontext()
        return _NoOpTracer()
