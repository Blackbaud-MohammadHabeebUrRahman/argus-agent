from __future__ import annotations

import logging

from argus.alert.dedup import AlertDedup
from argus.alert.router import AlertRouter
from argus.config import ArgusConfig
from argus.metrics import ALERTS_SENT, INCIDENTS_OPENED, INCIDENTS_RESOLVED
from argus.models import CheckResult, CheckStatus
from argus.plugins import Hub, build_hub

from .scheduler import CheckScheduler
from .state import IncidentStore

logger = logging.getLogger(__name__)


class ArgusEngine:
    """Central orchestrator: detect -> evaluate state -> route alert.

    Check types are resolved through a ``Hub``; core checks (http, redis)
    are always available, and product plugins contribute additional ones
    like ``saboten.job_health``.
    """

    def __init__(self, config: ArgusConfig, hub: Hub | None = None):
        self._config = config
        self._hub = hub or build_hub(enabled_products=config.enabled_products)
        self._incident_store = IncidentStore(config.settings.redis_url)
        self._dedup = AlertDedup(
            config.settings.redis_url,
            cooldown_minutes=config.alerting.dedup.cooldown_minutes,
        )
        self._router = AlertRouter(config.alerting)
        self._scheduler = CheckScheduler(on_result=self._on_check_result)

        self._register_checks()

    def _register_checks(self) -> None:
        env_config = self._config.active_env
        env_name = self._config.settings.environment

        for svc_name, svc_cfg in env_config.services.items():
            for chk_cfg in svc_cfg.checks:
                check_name = f"{svc_name}-{chk_cfg.type}"
                if len(svc_cfg.checks) > 1:
                    # Disambiguate when a service has multiple checks of the same type
                    same_type = [c for c in svc_cfg.checks if c.type == chk_cfg.type]
                    if len(same_type) > 1:
                        idx = same_type.index(chk_cfg)
                        check_name = f"{svc_name}-{chk_cfg.type}-{idx}"

                factory = self._hub.get_check_factory(chk_cfg.type)
                if factory is None:
                    logger.warning(
                        "Unknown check type %r for %s — skipping (available: %s)",
                        chk_cfg.type,
                        svc_name,
                        self._hub.check_types(),
                    )
                    continue

                check = factory(check_name, svc_name, svc_cfg, chk_cfg, env_name)
                self._scheduler.register(check)

    async def _on_check_result(self, result: CheckResult) -> None:
        logger.debug(
            "Check %s/%s: %s — %s",
            result.service,
            result.check_name,
            result.status.value,
            result.message,
        )

        if result.status == CheckStatus.OK:
            # Resolve any active incident for this check
            dedup_key = f"{result.check_name}:{result.service}:{result.environment}"
            active = await self._incident_store.get_active(dedup_key)
            if active:
                await self._incident_store.resolve(dedup_key)
                await self._dedup.clear(dedup_key)
                INCIDENTS_RESOLVED.labels(service=result.service).inc()
                logger.info("Resolved incident for %s/%s", result.service, result.check_name)
            return

        incident, is_new = await self._incident_store.create_or_update(result)
        if is_new:
            INCIDENTS_OPENED.labels(
                service=incident.service, severity=incident.severity.value
            ).inc()

        if not await self._dedup.should_alert(incident.dedup_key, incident.severity):
            logger.debug("Dedup cooldown active for %s — suppressing alert", incident.dedup_key)
            return

        channels_fired = await self._router.dispatch(incident)
        if channels_fired:
            await self._dedup.mark_alerted(incident.dedup_key, incident.severity)
            for channel_name in channels_fired:
                ALERTS_SENT.labels(channel=channel_name).inc()
            logger.info(
                "Alert dispatched for %s/%s to %d channel(s) [%s]",
                incident.service,
                incident.check_name,
                len(channels_fired),
                "NEW" if is_new else "UPDATE",
            )

    async def start(self) -> None:
        logger.info("ArgusEngine starting...")
        await self._scheduler.start()

    async def stop(self) -> None:
        logger.info("ArgusEngine stopping...")
        await self._scheduler.stop()
        await self._incident_store.close()
        await self._dedup.close()
