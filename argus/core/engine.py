from __future__ import annotations

import logging

from argus.alert.dedup import AlertDedup
from argus.alert.router import AlertRouter
from argus.config import ArgusConfig
from argus.models import CheckResult, CheckStatus
from argus.monitor.http_check import HttpCheck
from argus.monitor.job_check import JobCheck
from argus.monitor.redis_check import RedisCheck

from .scheduler import CheckScheduler
from .state import IncidentStore

logger = logging.getLogger(__name__)

CHECK_FACTORIES = {
    "http": lambda name, svc_name, svc_cfg, chk_cfg, env: HttpCheck(
        name=name,
        service=svc_name,
        host=svc_cfg.host,
        port=chk_cfg.port,
        path=chk_cfg.path,
        interval=chk_cfg.interval,
        timeout=chk_cfg.timeout,
        environment=env,
        thresholds=chk_cfg.thresholds,
    ),
    "job_health": lambda name, svc_name, svc_cfg, chk_cfg, env: JobCheck(
        name=name,
        service=svc_name,
        host=svc_cfg.host,
        port=chk_cfg.port,
        path=chk_cfg.path or "/monitor",
        interval=chk_cfg.interval,
        timeout=chk_cfg.timeout,
        environment=env,
        thresholds=chk_cfg.thresholds,
    ),
    "redis": lambda name, svc_name, svc_cfg, chk_cfg, env: RedisCheck(
        name=name,
        service=svc_name,
        host=svc_cfg.host,
        port=chk_cfg.port,
        interval=chk_cfg.interval,
        timeout=chk_cfg.timeout,
        environment=env,
        thresholds=chk_cfg.thresholds,
    ),
}


class ArgusEngine:
    """Central orchestrator: detect -> evaluate state -> route alert."""

    def __init__(self, config: ArgusConfig):
        self._config = config
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

                factory = CHECK_FACTORIES.get(chk_cfg.type)
                if factory is None:
                    logger.warning(
                        "Unknown check type '%s' for %s — skipping",
                        chk_cfg.type,
                        svc_name,
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
                logger.info("Resolved incident for %s/%s", result.service, result.check_name)
            return

        incident, is_new = await self._incident_store.create_or_update(result)

        if not await self._dedup.should_alert(incident.dedup_key):
            logger.debug("Dedup cooldown active for %s — suppressing alert", incident.dedup_key)
            return

        sent = await self._router.dispatch(incident)
        if sent > 0:
            await self._dedup.mark_alerted(incident.dedup_key)
            logger.info(
                "Alert dispatched for %s/%s to %d channel(s) [%s]",
                incident.service,
                incident.check_name,
                sent,
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
