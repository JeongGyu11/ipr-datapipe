"""FastAPI lifespan APScheduler adapter for the collection use-case."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.application.collection import (
    CollectionApplication,
    CollectionRequest,
    CollectionResult,
)
from app.config_paths import resolve_config_path
from app.core.ipr_logger import get_logger
from app.core.settings import get_settings
from crawler.adapters import ADAPTER_REGISTRY
from crawler.company_catalog import validate_company_selection
from crawler.config import load_config
from utils.date_utils import month_range


LOGGER = get_logger(__name__)


def _optional_env(name: str) -> str | None:
    """Legacy helper retained for callers importing it indirectly."""
    import os
    value = os.getenv(name)
    return value.strip() or None if value is not None else None


@dataclass(frozen=True)
class SchedulerSettings:
    """환경변수로 주입하는 cron과 수집 request 설정."""

    cron: str
    timezone: str = "Asia/Seoul"
    config_path: str = "config.yaml"
    period_mode: str = "previous_day"
    target_month: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    companies: tuple[str, ...] = ()
    misfire_grace_time: int = 3600

    @classmethod
    def from_env(
        cls,
        env_file: str | Path | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "SchedulerSettings":
        core = get_settings(env_file=env_file, environ=environ).scheduler
        return cls(
            cron=core.cron,
            timezone=core.timezone,
            config_path=core.config_path,
            period_mode=core.period_mode,
            target_month=core.target_month,
            start_date=core.start_date,
            end_date=core.end_date,
            companies=core.companies,
            misfire_grace_time=core.misfire_grace_time,
        )

    def _validated_company_codes(self) -> tuple[str, ...]:
        return validate_company_selection(self.companies, ADAPTER_REGISTRY)

    def collector_request(self, *, now: datetime | None = None) -> CollectionRequest:
        target_month = (self.target_month or "").strip() or None
        start_date = (self.start_date or "").strip() or None
        end_date = (self.end_date or "").strip() or None
        if target_month and (start_date or end_date):
            raise ValueError(
                "IPR_SCHEDULE_TARGET_MONTH와 START_DATE/END_DATE는 함께 지정할 수 없습니다"
            )
        if not target_month and not start_date and not end_date and self.period_mode == "previous_day":
            reference = now or datetime.now(ZoneInfo(self.timezone))
            previous_day = (reference.date() - timedelta(days=1)).isoformat()
            start_date = previous_day
            end_date = previous_day
        elif not target_month and not start_date and not end_date and self.period_mode == "config":
            config = load_config(resolve_config_path(self.config_path))
            if not config.target_month:
                raise ValueError(
                    "IPR_SCHEDULE_PERIOD_MODE=config을 사용하려면 config의 target_month가 필요합니다"
                )
            month_range(config.target_month)
        elif not target_month and not start_date and not end_date:
            raise ValueError("IPR_SCHEDULE_PERIOD_MODE는 previous_day 또는 config여야 합니다")
        request = CollectionRequest(
            config_path=resolve_config_path(self.config_path),
            target_month=target_month,
            start_date=start_date,
            end_date=end_date,
            companies=self._validated_company_codes(),
        )
        request.validate_shape()
        return request


def run_collection(
    request: CollectionRequest,
    *,
    application: CollectionApplication | None = None,
) -> CollectionResult:
    """Invoke the shared application directly from the scheduler thread."""

    result = (application or CollectionApplication()).run(request)
    if result.exit_code == 4 and result.error == "collection advisory lock unavailable":
        LOGGER.info("scheduled collection skipped: another run holds the advisory lock")
        return CollectionResult(0, "SKIPPED", error=result.error)
    if result.exit_code:
        LOGGER.error("scheduled collection finished with exit code %s", result.exit_code)
    return result


def create_scheduler(
    settings: SchedulerSettings | None = None,
    *,
    job: Callable[[], CollectionResult | int] | None = None,
) -> BackgroundScheduler:
    """Create the single in-process scheduled collection job."""

    settings = settings or SchedulerSettings.from_env()
    # Invalid period/configuration must fail application startup rather than
    # surfacing later in the APScheduler worker thread.
    settings.collector_request()
    timezone = ZoneInfo(settings.timezone)
    scheduler = BackgroundScheduler(timezone=timezone)
    scheduled_job = job or (lambda: run_collection(settings.collector_request()))
    trigger = CronTrigger.from_crontab(settings.cron, timezone=timezone)
    scheduler.add_job(
        scheduled_job,
        trigger=trigger,
        id="scheduled-collection",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=settings.misfire_grace_time,
    )
    return scheduler


__all__ = [
    "SchedulerSettings",
    "create_scheduler",
    "run_collection",
]
