"""Load a local ``.env`` file into process env vars if present.

Development convenience only. In production, secrets come from the
platform's own mechanism (AWS Secrets Manager, Kubernetes secrets,
HashiCorp Vault); no ``.env`` ships with a deployed container. If
``python-dotenv`` isn't installed this is a silent no-op.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def load_dotenv_if_present(path: str | Path = ".env") -> bool:
    """Return True if a ``.env`` was found and loaded."""
    env_path = Path(path)
    if not env_path.is_file():
        return False
    try:
        from dotenv import load_dotenv as _load_dotenv
    except ImportError:
        logger.debug("python-dotenv not installed; skipping %s", env_path)
        return False
    _load_dotenv(env_path, override=False)
    # Report by name only — never echo the value.
    present = [k for k in ("ANTHROPIC_API_KEY", "ARGUS_ANTHROPIC_API_KEY") if os.getenv(k)]
    logger.info(
        "loaded %s (vars present: %s)",
        env_path,
        ", ".join(present) if present else "none we care about",
    )
    return True
