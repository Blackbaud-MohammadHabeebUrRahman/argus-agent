from __future__ import annotations

import logging

from sentinel.config import AlertingConfig
from sentinel.models import Incident

from .base import AlertChannel
from .slack import SlackChannel
from .teams import TeamsChannel

logger = logging.getLogger(__name__)


class AlertRouter:
    """Routes incidents to alert channels based on severity and config rules."""

    def __init__(self, config: AlertingConfig):
        self._channels: dict[str, AlertChannel] = {}
        self._rules = config.routing

        if config.teams.enabled and config.teams.webhook_url:
            self._channels["teams"] = TeamsChannel(webhook_url=config.teams.webhook_url)
            logger.info("Teams alert channel enabled")

        if config.slack.enabled and config.slack.webhook_url:
            self._channels["slack"] = SlackChannel(
                webhook_url=config.slack.webhook_url,
                channel=config.slack.channel,
            )
            logger.info("Slack alert channel enabled")

        if not self._channels:
            logger.warning("No alert channels configured — alerts will only be logged")

    def _channels_for_severity(self, severity: str) -> list[AlertChannel]:
        for rule in self._rules:
            if rule.severity == severity:
                return [self._channels[ch] for ch in rule.channels if ch in self._channels]
        return list(self._channels.values())

    async def dispatch(self, incident: Incident) -> int:
        """Dispatch an incident to the appropriate channels. Returns count of successful sends."""
        channels = self._channels_for_severity(incident.severity.value)

        if not channels:
            logger.info(
                "No channels matched severity=%s for %s/%s — logging only",
                incident.severity.value,
                incident.service,
                incident.check_name,
            )
            return 0

        sent = 0
        for channel in channels:
            try:
                success = await channel.send(incident)
                if success:
                    sent += 1
            except Exception:
                logger.exception(
                    "Error dispatching to %s for %s/%s",
                    channel.name,
                    incident.service,
                    incident.check_name,
                )
        return sent
