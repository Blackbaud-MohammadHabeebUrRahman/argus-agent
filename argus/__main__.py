from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal

from .config import load_config
from .core.engine import ArgusEngine
from .logging import configure_logging
from .metrics import start_metrics_server
from .telemetry import configure_tracing

logger = logging.getLogger("argus")


async def _run() -> None:
    config = load_config()
    configure_logging(
        level=config.settings.log_level,
        json_output=os.getenv("ARGUS_LOG_JSON", "1") != "0",
    )
    configure_tracing()
    if config.metrics.enabled:
        start_metrics_server(config.metrics.port, addr=config.metrics.addr)
    logger.info("Argus starting", extra={"env": config.settings.environment})

    engine = ArgusEngine(config)
    loop = asyncio.get_running_loop()

    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _handle_signal())

    await engine.start()
    logger.info("Argus is running. Press Ctrl+C to stop.")
    await stop_event.wait()
    await engine.stop()
    logger.info("Argus stopped.")


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run())


if __name__ == "__main__":
    main()
