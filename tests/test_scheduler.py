from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from app.application.collection import CollectionRequest, CollectionResult
from app.config_paths import resolve_config_path
from app.scheduling.scheduler import SchedulerSettings, create_scheduler, run_collection
from app.core.settings import get_settings


def test_run_collection_calls_application_directly() -> None:
    events: list[str] = []
    request = CollectionRequest(config_path=Path("config.yaml"), target_month="2026-08")

    class Application:
        def run(self, received):
            events.append("run")
            assert received is request
            return CollectionResult(7, "FAILED", error="test")

    result = run_collection(request, application=Application())

    assert result.exit_code == 7
    assert events == ["run"]


def test_scheduler_translates_global_lock_contention_to_skip() -> None:
    request = CollectionRequest(config_path=Path("config.yaml"))

    class Application:
        def run(self, _request):
            return CollectionResult(4, "LOCKED", error="collection advisory lock unavailable")

    result = run_collection(request, application=Application())

    assert result.exit_code == 0
    assert result.status == "SKIPPED"


def test_settings_build_target_month_request() -> None:
    settings = SchedulerSettings(
        cron="0 3 * * *",
        config_path="config.container.yaml",
        target_month="2026-08",
        companies=("DB", "KB"),
    )

    request = settings.collector_request()
    assert request.config_path == resolve_config_path("config.container.yaml")
    assert request.target_month == "2026-08"
    assert request.start_date is None
    assert request.companies == ("DB", "KB")


def test_settings_reject_target_month_and_date_range_together() -> None:
    settings = SchedulerSettings(
        cron="0 3 * * *",
        target_month="2026-08",
        start_date="2026-08-01",
        end_date="2026-08-31",
    )

    with pytest.raises(ValueError, match="TARGET_MONTH.*START_DATE/END_DATE"):
        settings.collector_request()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_month", "2026-13"),
        ("start_date", "2026-02-30"),
        ("end_date", "2026/08/31"),
    ],
)
def test_settings_reject_invalid_period_values(field: str, value: str) -> None:
    values = {"cron": "0 3 * * *", field: value}
    if field in {"start_date", "end_date"}:
        values.update(start_date="2026-08-01", end_date="2026-08-31")
        values[field] = value
    settings = SchedulerSettings(**values)

    with pytest.raises(ValueError):
        settings.collector_request()


def test_settings_normalize_blank_period_environment_values(monkeypatch) -> None:
    monkeypatch.setenv("IPR_SCHEDULE_TARGET_MONTH", "  ")
    monkeypatch.setenv("IPR_SCHEDULE_START_DATE", " \t")
    monkeypatch.setenv("IPR_SCHEDULE_END_DATE", "")

    get_settings(reload=True)
    settings = SchedulerSettings.from_env()

    assert settings.target_month is None
    assert settings.start_date is None
    assert settings.end_date is None


def test_settings_config_period_requires_target_month(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("target_month: null\n", encoding="utf-8")
    settings = SchedulerSettings(
        cron="0 3 * * *", config_path=str(config_path), period_mode="config"
    )

    with pytest.raises(ValueError, match="target_month가 필요합니다"):
        settings.collector_request()


def test_settings_config_period_rejects_invalid_config_target_month(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("target_month: '2026-13'\n", encoding="utf-8")
    settings = SchedulerSettings(
        cron="0 3 * * *", config_path=str(config_path), period_mode="config"
    )

    with pytest.raises(ValueError):
        settings.collector_request()


def test_create_scheduler_validates_collection_request_at_startup() -> None:
    settings = SchedulerSettings(cron="0 3 * * *", target_month="2026-13")

    with pytest.raises(ValueError):
        create_scheduler(settings, job=lambda: 0)


def test_create_scheduler_rejects_config_mode_without_target_month(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("target_month: null\n", encoding="utf-8")
    settings = SchedulerSettings(
        cron="0 3 * * *",
        config_path=str(config_path),
        period_mode="config",
    )

    with pytest.raises(ValueError, match="target_month가 필요합니다"):
        create_scheduler(settings, job=lambda: 0)


def test_settings_use_previous_day_by_default() -> None:
    settings = SchedulerSettings(cron="0 3 * * *", timezone="Asia/Seoul")

    request = settings.collector_request(now=datetime(2026, 8, 26, 3, 0))
    assert request.start_date == "2026-08-25"
    assert request.end_date == "2026-08-25"


def test_settings_can_delegate_period_to_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("target_month: '2026-08'\n", encoding="utf-8")
    settings = SchedulerSettings(
        cron="0 3 * * *", config_path=str(config_path), period_mode="config"
    )

    request = settings.collector_request()
    assert request.start_date is None
    assert request.target_month is None


def test_settings_normalizes_and_validates_catalog_company_codes() -> None:
    settings = SchedulerSettings(cron="0 3 * * *", companies=("db", " kb "))

    assert settings.collector_request().companies == ("DB", "KB")


def test_settings_rejects_unknown_catalog_company_code() -> None:
    settings = SchedulerSettings(cron="0 3 * * *", companies=("NOT_A_COMPANY",))

    try:
        settings.collector_request()
    except ValueError as exc:
        assert "등록되지 않은 보험사 코드" in str(exc)
    else:
        raise AssertionError("unknown company must be rejected")


def test_settings_rejects_non_active_catalog_company_code() -> None:
    from crawler.company_catalog import COMPANY_BY_CODE

    restricted = next(
        company
        for company in COMPANY_BY_CODE.values()
        if getattr(getattr(company, "collection_status", None), "value", None) != "ACTIVE"
    )
    settings = SchedulerSettings(cron="0 3 * * *", companies=(restricted.code,))

    with pytest.raises(ValueError, match="접근 제한 상태"):
        settings.collector_request()


def test_scheduler_has_one_non_persistent_collection_job() -> None:
    scheduler = create_scheduler(SchedulerSettings(cron="0 3 * * *"), job=lambda: 0)

    assert isinstance(scheduler, BackgroundScheduler)
    job = scheduler.get_job("scheduled-collection")
    assert job is not None
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.misfire_grace_time == 3600
    assert scheduler.running is False
