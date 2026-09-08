from __future__ import annotations

from pathlib import Path

import pytest

from app.load_settings import (
    DEFAULT_HEADER_FOOTER_ENABLED,
    DEFAULT_TABLE_RECONSTRUCTION_ENABLED,
    PDF_LOAD_HEADER_FOOTER_ENV,
    PDF_LOAD_TABLE_RECONSTRUCTION_ENV,
    PdfLoadSettings,
    PdfLoadSettingsError,
    parse_boolean,
)


@pytest.mark.parametrize("value", ["true", "TRUE", " true ", "1", "on", "yes"])
def test_parse_boolean_accepts_true_aliases(value: str) -> None:
    assert parse_boolean(value) is True


@pytest.mark.parametrize("value", ["false", "FALSE", " false ", "0", "off", "no"])
def test_parse_boolean_accepts_false_aliases(value: str) -> None:
    assert parse_boolean(value) is False


@pytest.mark.parametrize("value", ["", "maybe", "2", "enabled", None])
def test_parse_boolean_rejects_invalid_values(value: object) -> None:
    with pytest.raises(PdfLoadSettingsError, match=PDF_LOAD_HEADER_FOOTER_ENV):
        parse_boolean(value)


def test_from_env_defaults_to_disabled_when_file_and_os_are_unset(tmp_path: Path) -> None:
    settings = PdfLoadSettings.from_env(tmp_path / "missing.env", environ={})

    assert settings.header_footer_enabled is DEFAULT_HEADER_FOOTER_ENABLED
    assert (
        settings.table_reconstruction_enabled
        is DEFAULT_TABLE_RECONSTRUCTION_ENABLED
    )


def test_from_env_reads_table_reconstruction_toggle(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"{PDF_LOAD_TABLE_RECONSTRUCTION_ENV}=true\n"
        "LLM_BASE_URL=https://llm.example/v1\n"
        "LLM_MODEL=vision-model\n",
        encoding="utf-8",
    )

    settings = PdfLoadSettings.from_env(env_file, environ={})

    assert settings.table_reconstruction_enabled is True


@pytest.mark.parametrize("value", ["true", "1", "ON", "yes", "false", "0", "off", "NO"])
def test_from_env_reads_project_env_value(tmp_path: Path, value: str) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{PDF_LOAD_HEADER_FOOTER_ENV}={value}\n", encoding="utf-8")

    expected = value.strip().lower() in {"true", "1", "on", "yes"}
    settings = PdfLoadSettings.from_env(env_file, environ={})

    assert settings.header_footer_enabled is expected


def test_os_environment_takes_precedence_over_project_env(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{PDF_LOAD_HEADER_FOOTER_ENV}=false\n", encoding="utf-8")

    settings = PdfLoadSettings.from_env(
        env_file,
        environ={PDF_LOAD_HEADER_FOOTER_ENV: "on"},
    )

    assert settings.header_footer_enabled is True


def test_invalid_os_environment_is_not_hidden_by_project_env(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{PDF_LOAD_HEADER_FOOTER_ENV}=false\n", encoding="utf-8")

    with pytest.raises(PdfLoadSettingsError, match="허용값"):
        PdfLoadSettings.from_env(
            env_file,
            environ={PDF_LOAD_HEADER_FOOTER_ENV: "sometimes"},
        )


def test_invalid_project_env_is_reported(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{PDF_LOAD_HEADER_FOOTER_ENV}=\n", encoding="utf-8")

    with pytest.raises(PdfLoadSettingsError, match=PDF_LOAD_HEADER_FOOTER_ENV):
        PdfLoadSettings.from_env(env_file, environ={})
