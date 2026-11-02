from __future__ import annotations

import asyncio
import logging
import os
import signal

from .config import load_config
from .core.engine import SentinelEngine
from .logging import configure_logging
from .telemetry import configure_tracing

logger = logging.getLogger("sentinel")


async def _run() -> None:
    config = load_config()
    configure_logging(
        level=config.settings.log_level,
        json_output=os.getenv("SENTINEL_LOG_JSON", "1") != "0",
    )
    configure_tracing()
    logger.info(
        "Saboten Sentinel starting", extra={"env": config.settings.environment}
    )

    engine = SentinelEngine(config)
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
    logger.info("Sentinel is running. Press Ctrl+C to stop.")
    await stop_event.wait()
    await engine.stop()
    logger.info("Sentinel stopped.")


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
