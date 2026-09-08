from __future__ import annotations

from pathlib import Path

import pytest

from app.config_paths import PROJECT_ROOT
from app.core.settings import (
    SettingsError,
    get_settings,
    parse_boolean,
    parse_csv,
    parse_float,
    parse_int,
)


def test_precedence_and_nested_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "RS_DB_HOST=file-host\nIPR_SCHEDULE_COMPANIES=DB, KB\n"
        "PDF_LOAD_HEADER_FOOTER_ENABLED=false\n"
        "PDF_LOAD_TABLE_RECONSTRUCTION_ENABLED=false\n"
        "LOG_LEVEL=WARNING\n",
        encoding="utf-8",
    )
    settings = get_settings(env_file, {"RS_DB_HOST": "os-host", "PDF_LOAD_HEADER_FOOTER_ENABLED": "on"}, reload=True)
    assert settings.database.host == "os-host"
    assert settings.scheduler.companies == ("DB", "KB")
    assert settings.pdf_load.header_footer_enabled is True
    assert settings.pdf_load.table_reconstruction_enabled is False
    assert settings.logging.level == "WARNING"


def test_llm_settings_are_optional_when_table_reconstruction_is_disabled(
    tmp_path: Path,
) -> None:
    settings = get_settings(tmp_path / "missing.env", {}, reload=True)

    assert settings.pdf_load.table_reconstruction_enabled is False
    assert settings.llm.base_url is None
    assert settings.llm.model is None


def test_llm_settings_are_required_when_table_reconstruction_is_enabled(
    tmp_path: Path,
) -> None:
    with pytest.raises(SettingsError, match="LLM_BASE_URL, LLM_MODEL"):
        get_settings(
            tmp_path / "missing.env",
            {"PDF_LOAD_TABLE_RECONSTRUCTION_ENABLED": "true"},
            reload=True,
        )


def test_llm_settings_parse_and_hide_api_key(tmp_path: Path) -> None:
    settings = get_settings(
        tmp_path / "missing.env",
        {
            "PDF_LOAD_TABLE_RECONSTRUCTION_ENABLED": "true",
            "LLM_BASE_URL": "https://llm.example/v1",
            "LLM_MODEL": "vision-model",
            "LLM_API_KEY": "top-secret",
            "LLM_REQUEST_TIMEOUT_SECONDS": "30.5",
            "LLM_MAX_OUTPUT_TOKENS": "4096",
        },
        reload=True,
    )

    assert settings.llm.base_url == "https://llm.example/v1"
    assert settings.llm.model == "vision-model"
    assert settings.llm.request_timeout_seconds == 30.5
    assert settings.llm.max_output_tokens == 4096
    assert "top-secret" not in repr(settings)


def test_defaults_and_cwd_independence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = get_settings(tmp_path / "missing.env", {}, reload=True)
    assert settings.scheduler.cron == "0 3 * * *"
    assert settings.logging.log_dir == PROJECT_ROOT / "logs"


@pytest.mark.parametrize("parser,value", [(parse_boolean, "maybe"), (parse_int, "1.2"), (parse_float, "nan")])
def test_strict_scalar_parsers(parser, value) -> None:
    with pytest.raises(SettingsError):
        parser(value, variable_name="TEST_VALUE")


def test_csv_parser_and_strict_error() -> None:
    assert parse_csv(" DB, KB ,,", variable_name="COMPANIES") == ("DB", "KB")
    with pytest.raises(SettingsError):
        parse_csv('"unterminated', variable_name="COMPANIES")


def test_logging_validation_and_blank_dir(tmp_path: Path) -> None:
    with pytest.raises(SettingsError):
        get_settings(tmp_path / "bad.env", {"LOG_LEVEL": "VERBOSE"}, reload=True)
    settings = get_settings(tmp_path / "blank.env", {"IPR_LOG_DIR": ""}, reload=True)
    assert settings.logging.log_dir == PROJECT_ROOT / "logs"


def test_cache_reload_and_lazy_database_validation(tmp_path: Path) -> None:
    first = get_settings(tmp_path / "missing.env", {}, reload=True)
    assert get_settings(tmp_path / "missing.env", {}) is first
    second = get_settings(tmp_path / "missing.env", {}, reload=True)
    assert second is not first
    with pytest.raises(SettingsError):
        second.database.connect_kwargs()
    assert "secret" not in repr(get_settings(tmp_path / "db.env", {"RS_DB_PASSWORD": "secret"}, reload=True))


def test_process_environment_changes_require_reload(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "missing.env"
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    first = get_settings(env_file, reload=True)

    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    assert get_settings(env_file) is first
    assert get_settings(env_file).logging.level == "INFO"

    refreshed = get_settings(env_file, reload=True)
    assert refreshed.logging.level == "ERROR"
