from __future__ import annotations

import logging

import httpx

from sentinel.models import Incident, Severity

from .base import AlertChannel

logger = logging.getLogger(__name__)


class SlackChannel(AlertChannel):
    """Send alerts to Slack via incoming webhook (Block Kit)."""

    name = "slack"

    def __init__(self, webhook_url: str, channel: str = "#saboten-alerts", timeout: int = 15):
        self.webhook_url = webhook_url
        self.channel = channel
        self.timeout = timeout

    async def send(self, incident: Incident) -> bool:
        if not self.webhook_url:
            logger.warning("Slack webhook URL not configured — skipping")
            return False

        emoji = {
            Severity.INFO: ":information_source:",
            Severity.WARNING: ":warning:",
            Severity.CRITICAL: ":rotating_light:",
            Severity.FATAL: ":fire:",
        }.get(incident.severity, ":question:")

        detail_lines = []
        if incident.details:
            for key, value in list(incident.details.items())[:5]:
                detail_lines.append(f"*{key}:* {value}")

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} Saboten Sentinel Alert",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{incident.message}*",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Service:*\n{incident.service}"},
                    {"type": "mrkdwn", "text": f"*Check:*\n{incident.check_name}"},
                    {"type": "mrkdwn", "text": f"*Environment:*\n{incident.environment.upper()}"},
                    {"type": "mrkdwn", "text": f"*Severity:*\n{incident.severity.value.upper()}"},
                ],
            },
        ]

        if detail_lines:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "\n".join(detail_lines),
                    },
                }
            )

        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Detected at {incident.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')} | Incident {incident.id}",
                    }
                ],
            }
        )

        payload = {"blocks": blocks}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.webhook_url, json=payload)
                if resp.status_code == 200 and resp.text == "ok":
                    logger.info("Slack alert sent for %s/%s", incident.service, incident.check_name)
                    return True
                else:
                    logger.error(
                        "Slack webhook returned %d: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return False
        except Exception:
            logger.exception("Failed to send Slack alert")
            return False
