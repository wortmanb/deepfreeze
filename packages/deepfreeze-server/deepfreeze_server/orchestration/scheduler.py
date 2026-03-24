"""APScheduler integration for recurring deepfreeze jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..config import ScheduledJobConfig
from ..models.events import Event, EventChannel, EventType

if TYPE_CHECKING:
    from .orchestrator import DeepfreezeOrchestrator

logger = logging.getLogger("deepfreeze.server.scheduler")

# Built-in default: check thaw status every 60s
DEFAULT_JOBS = [
    ScheduledJobConfig(
        name="check-thaw-status",
        action="thaw_check",
        interval_seconds=60,
    ),
]


class DeepfreezeScheduler:
    """Manages recurring scheduled jobs using APScheduler.

    Built-in job: `check-thaw-status` runs every 60s to auto-complete
    in-progress thaw requests (replaces the hidden _auto_check_thaw
    side effect from the old DeepfreezeService).

    User-configurable jobs are loaded from the server config YAML.
    """

    def __init__(self, orchestrator: DeepfreezeOrchestrator) -> None:
        self._orch = orchestrator
        self._scheduler = AsyncIOScheduler()
        self._job_configs: dict[str, ScheduledJobConfig] = {}

    async def start(self, extra_jobs: list[ScheduledJobConfig] | None = None) -> None:
        """Register default + config-driven jobs and start the scheduler."""
        all_jobs = list(DEFAULT_JOBS)
        if extra_jobs:
            all_jobs.extend(extra_jobs)

        for job_cfg in all_jobs:
            self._add_job(job_cfg)

        self._scheduler.start()
        logger.info(
            "Scheduler started with %d job(s): %s",
            len(self._job_configs),
            ", ".join(self._job_configs.keys()),
        )

    async def stop(self) -> None:
        """Shut down the scheduler."""
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    # -- Job management API --

    def list_jobs(self) -> list[dict[str, Any]]:
        """List all scheduled jobs with their state."""
        result = []
        for name, cfg in self._job_configs.items():
            ap_job = self._scheduler.get_job(name)
            next_run = None
            if ap_job and ap_job.next_run_time:
                next_run = ap_job.next_run_time.isoformat()
            result.append({
                "name": name,
                "action": cfg.action,
                "params": cfg.params,
                "cron": cfg.cron,
                "interval_seconds": cfg.interval_seconds,
                "paused": ap_job is not None and ap_job.next_run_time is None,
                "next_run": next_run,
            })
        return result

    def add_job(self, cfg: ScheduledJobConfig) -> dict[str, Any]:
        """Add a new scheduled job at runtime."""
        if cfg.name in self._job_configs:
            raise ValueError(f"Job '{cfg.name}' already exists")
        self._add_job(cfg)
        return {"name": cfg.name, "status": "added"}

    def remove_job(self, name: str) -> bool:
        """Remove a scheduled job. Returns True if removed."""
        if name not in self._job_configs:
            return False
        self._scheduler.remove_job(name)
        del self._job_configs[name]
        logger.info("Removed scheduled job: %s", name)
        return True

    def pause_job(self, name: str) -> bool:
        """Pause a scheduled job."""
        if name not in self._job_configs:
            return False
        self._scheduler.pause_job(name)
        logger.info("Paused scheduled job: %s", name)
        return True

    def resume_job(self, name: str) -> bool:
        """Resume a paused scheduled job."""
        if name not in self._job_configs:
            return False
        self._scheduler.resume_job(name)
        logger.info("Resumed scheduled job: %s", name)
        return True

    # -- Internal --

    def _add_job(self, cfg: ScheduledJobConfig) -> None:
        """Register a job with APScheduler."""
        trigger = self._make_trigger(cfg)
        if trigger is None:
            logger.warning("Skipping job '%s': no cron or interval_seconds", cfg.name)
            return

        self._scheduler.add_job(
            self._execute_scheduled_action,
            trigger=trigger,
            id=cfg.name,
            name=cfg.name,
            kwargs={"job_name": cfg.name, "action": cfg.action, "params": cfg.params},
            replace_existing=True,
        )
        self._job_configs[cfg.name] = cfg

    @staticmethod
    def _make_trigger(cfg: ScheduledJobConfig):
        """Build an APScheduler trigger from config."""
        if cfg.cron:
            return CronTrigger.from_crontab(cfg.cron)
        if cfg.interval_seconds:
            return IntervalTrigger(seconds=cfg.interval_seconds)
        return None

    async def _execute_scheduled_action(
        self, job_name: str, action: str, params: dict
    ) -> None:
        """Run a scheduled action through the orchestrator's job manager."""
        logger.debug("Scheduler firing: %s (%s)", job_name, action)

        await self._orch.event_bus.publish(Event(
            type=EventType.SCHEDULER_FIRED,
            channel=EventChannel.SCHEDULER,
            data={"job_name": job_name, "action": action},
        ))

        # Map action names to orchestrator methods
        action_map = {
            "rotate": self._orch.rotate,
            "thaw_check": self._orch.thaw_check,
            "cleanup": self._orch.cleanup,
            "repair": self._orch.repair_metadata,
            "refreeze": self._orch.refreeze,
        }

        method = action_map.get(action)
        if not method:
            logger.error("Unknown scheduled action: %s", action)
            return

        try:
            await method(**params)
        except Exception as e:
            logger.error("Scheduled job '%s' failed: %s", job_name, e)
