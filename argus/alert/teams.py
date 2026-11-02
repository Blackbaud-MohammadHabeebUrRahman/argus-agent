from __future__ import annotations

import logging

import httpx

from argus.models import Incident, Severity

from .base import AlertChannel

logger = logging.getLogger(__name__)


class TeamsChannel(AlertChannel):
    """Send alerts to Microsoft Teams via incoming webhook (Adaptive Cards)."""

    name = "teams"

    def __init__(self, webhook_url: str, timeout: int = 15):
        self.webhook_url = webhook_url
        self.timeout = timeout

    async def send(self, incident: Incident) -> bool:
        if not self.webhook_url:
            logger.warning("Teams webhook URL not configured — skipping")
            return False

        emoji = {
            Severity.INFO: "ℹ️",
            Severity.WARNING: "⚠️",
            Severity.CRITICAL: "🚨",
            Severity.FATAL: "🔥",
        }.get(incident.severity, "❓")

        facts = [
            {"title": "Service", "value": incident.service},
            {"title": "Check", "value": incident.check_name},
            {"title": "Environment", "value": incident.environment.upper()},
            {"title": "Severity", "value": incident.severity.value.upper()},
            {"title": "Time (UTC)", "value": incident.created_at.strftime("%Y-%m-%d %H:%M:%S")},
        ]

        if incident.details:
            for key, value in list(incident.details.items())[:5]:
                facts.append({"title": key, "value": str(value)})

        card = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "msteams": {"width": "Full"},
                        "body": [
                            {
                                "type": "Container",
                                "style": "emphasis"
                                if incident.severity in (Severity.CRITICAL, Severity.FATAL)
                                else "default",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": f"{emoji} Argus Alert",
                                        "weight": "Bolder",
                                        "size": "Medium",
                                        "color": "Attention"
                                        if incident.severity in (Severity.CRITICAL, Severity.FATAL)
                                        else "Warning"
                                        if incident.severity == Severity.WARNING
                                        else "Default",
                                    },
                                ],
                            },
                            {
                                "type": "TextBlock",
                                "text": incident.message,
                                "wrap": True,
                                "weight": "Bolder",
                            },
                            {
                                "type": "FactSet",
                                "facts": facts,
                            },
                        ],
                    },
                }
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.webhook_url, json=card)
                if resp.status_code in (200, 202):
                    logger.info("Teams alert sent for %s/%s", incident.service, incident.check_name)
                    return True
                else:
                    logger.error(
                        "Teams webhook returned %d: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return False
        except Exception:
            logger.exception("Failed to send Teams alert")
            return False
