from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from sentinel.models import Incident

logger = logging.getLogger(__name__)


class AlertChannel(ABC):
    """Base class for all alert channels."""

    name: str = "base"

    @abstractmethod
    async def send(self, incident: Incident) -> bool:
        """Send an alert for the given incident. Returns True on success."""
        ...
