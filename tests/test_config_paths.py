from __future__ import annotations

from pathlib import Path

from app.api.dependencies import config_file_path
from app.config_paths import DEFAULT_CONFIG_PATH, PROJECT_ROOT, resolve_config_path
from app.core.settings import get_settings
from app.scheduling.scheduler import SchedulerSettings


def test_resolve_config_path_defaults_to_project_root(monkeypatch) -> None:
    monkeypatch.delenv("CRAWLER_CONFIG_PATH", raising=False)

    assert resolve_config_path() == DEFAULT_CONFIG_PATH.resolve()


def test_resolve_config_path_uses_env_and_project_root_for_relative_values(monkeypatch) -> None:
    monkeypatch.setenv("CRAWLER_CONFIG_PATH", "config.container.yaml")

    assert resolve_config_path() == (PROJECT_ROOT / "config.container.yaml").resolve()


def test_resolve_config_path_preserves_absolute_env_value(monkeypatch, tmp_path: Path) -> None:
    configured = tmp_path / "custom.yaml"
    monkeypatch.setenv("CRAWLER_CONFIG_PATH", str(configured))

    assert resolve_config_path() == configured.resolve()


def test_explicit_path_takes_precedence_over_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CRAWLER_CONFIG_PATH", "from-env.yaml")

    assert resolve_config_path(tmp_path / "explicit.yaml") == (tmp_path / "explicit.yaml").resolve()


def test_api_and_scheduler_use_same_project_root_path_outside_repo(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CRAWLER_CONFIG_PATH", "config.container.yaml")
    monkeypatch.setenv("IPR_SCHEDULE_TARGET_MONTH", "2026-08")
    monkeypatch.delenv("IPR_SCHEDULE_START_DATE", raising=False)
    monkeypatch.delenv("IPR_SCHEDULE_END_DATE", raising=False)

    expected = (PROJECT_ROOT / "config.container.yaml").resolve()
    get_settings(reload=True)
    settings = SchedulerSettings.from_env()

    assert config_file_path() == expected
    assert settings.collector_request().config_path == expected


def test_scheduler_api_value_keeps_config_path_source_text(monkeypatch) -> None:
    monkeypatch.setenv("CRAWLER_CONFIG_PATH", "./configs/custom.yaml")

    get_settings(reload=True)
    settings = SchedulerSettings.from_env()

    assert settings.config_path == "./configs/custom.yaml"
