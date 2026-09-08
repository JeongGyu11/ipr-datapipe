"""Immutable application settings with explicit, side-effect free loading.

Environment values are read (never injected into ``os.environ``) with the
following precedence: process environment, project ``.env``, then defaults.
Database credentials are intentionally optional at parse time so PDF Load can
run without a database; callers opening a connection must call
``DatabaseSettings.validate_for_connection``.
"""

from __future__ import annotations

import os
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

from app.config_paths import PROJECT_ROOT


class SettingsError(ValueError):
    """Raised when an environment setting cannot be parsed or validated."""


_TRUE = frozenset({"true", "1", "on", "yes"})
_FALSE = frozenset({"false", "0", "off", "no"})


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def parse_boolean(value: object, *, variable_name: str = "setting") -> bool:
    normalized = _text(value).lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise SettingsError(
        f"{variable_name} 값이 올바르지 않습니다: {value!r}. "
        "허용값: true, false, 1, 0, on, off, yes, no"
    )


# Short spelling retained for callers that use conventional parser names.
parse_bool = parse_boolean


def parse_int(value: object, *, variable_name: str = "setting") -> int:
    text = _text(value)
    try:
        if not text or any(ch in text.lower() for ch in (".", "e")):
            raise ValueError
        return int(text, 10)
    except (TypeError, ValueError):
        raise SettingsError(f"{variable_name} 값이 정수가 아닙니다: {value!r}") from None


def parse_float(value: object, *, variable_name: str = "setting") -> float:
    text = _text(value)
    try:
        result = float(text)
    except (TypeError, ValueError):
        raise SettingsError(f"{variable_name} 값이 실수가 아닙니다: {value!r}") from None
    if result != result or result in (float("inf"), float("-inf")):
        raise SettingsError(f"{variable_name} 값이 유한한 실수가 아닙니다: {value!r}")
    return result


def parse_csv(value: object, *, variable_name: str = "setting") -> tuple[str, ...]:
    """Parse a comma-separated list, trimming whitespace and empty entries."""
    if value is None:
        return ()
    try:
        rows = list(csv.reader([str(value)], strict=True))
    except csv.Error:
        raise SettingsError(f"{variable_name} CSV 값이 올바르지 않습니다: {value!r}") from None
    return tuple(part.strip() for part in (rows[0] if rows else ()) if part.strip())


def _resolve_env_file(env_file: str | Path | None) -> Path:
    path = Path(env_file) if env_file is not None else PROJECT_ROOT / ".env"
    return path if path.is_absolute() else PROJECT_ROOT / path


def _values(env_file: str | Path | None, environ: Mapping[str, str] | None) -> dict[str, object]:
    file_values: Mapping[str, object] = {}
    path = _resolve_env_file(env_file)
    if path.is_file():
        file_values = dotenv_values(path)
    process = os.environ if environ is None else environ
    merged: dict[str, object] = dict(file_values)
    merged.update(process)
    return merged


def _get(values: Mapping[str, object], name: str, default: object = None) -> object:
    return values[name] if name in values else default


@dataclass(frozen=True, repr=False)
class DatabaseSettings:
    host: str | None = None
    port: int | None = None
    user: str | None = None
    password: str | None = None
    dbname: str | None = None
    connect_timeout: int = 10
    sslmode: str | None = None

    @classmethod
    def from_env(cls, env_file: str | Path | None = None, *, environ: Mapping[str, str] | None = None) -> "DatabaseSettings":
        return get_settings(env_file=env_file, environ=environ).database

    def __repr__(self) -> str:
        masked = "***" if self.password else None
        return ("DatabaseSettings(host={!r}, port={!r}, user={!r}, password={!r}, "
                "dbname={!r}, connect_timeout={!r}, sslmode={!r})").format(
                    self.host, self.port, self.user, masked, self.dbname,
                    self.connect_timeout, self.sslmode)

    def validate_for_connection(self) -> "DatabaseSettings":
        required = {"RS_DB_HOST": self.host, "RS_DB_PORT": self.port, "RS_DB_USER": self.user,
                    "RS_DB_PASSWORD": self.password, "RS_DB_NAME": self.dbname}
        missing = [name for name, value in required.items() if value is None or not str(value).strip()]
        if missing:
            raise SettingsError("DB 설정이 비어 있습니다: " + ", ".join(missing))
        return self

    def connect_kwargs(self) -> dict[str, object]:
        self.validate_for_connection()
        result: dict[str, object] = {
            "host": self.host, "port": self.port, "user": self.user,
            "password": self.password, "dbname": self.dbname,
            "connect_timeout": self.connect_timeout, "autocommit": True,
        }
        if self.sslmode:
            result["sslmode"] = self.sslmode
        return result


@dataclass(frozen=True)
class SchedulerSettings:
    cron: str = "0 3 * * *"
    timezone: str = "Asia/Seoul"
    config_path: str = "config.yaml"
    period_mode: str = "previous_day"
    target_month: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    companies: tuple[str, ...] = ()
    misfire_grace_time: int = 3600

    @classmethod
    def from_env(cls, env_file: str | Path | None = None, *, environ: Mapping[str, str] | None = None) -> "SchedulerSettings":
        return get_settings(env_file=env_file, environ=environ).scheduler


@dataclass(frozen=True)
class PdfLoadSettings:
    header_footer_enabled: bool = False
    table_reconstruction_enabled: bool = False

    @classmethod
    def from_env(cls, env_file: str | Path | None = None, *, environ: Mapping[str, str] | None = None) -> "PdfLoadSettings":
        return get_settings(env_file=env_file, environ=environ).pdf_load


@dataclass(frozen=True, repr=False)
class LlmSettings:
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    request_timeout_seconds: float = 120.0
    max_output_tokens: int = 8192

    def __repr__(self) -> str:
        masked = "***" if self.api_key else None
        return (
            "LlmSettings(base_url={!r}, model={!r}, api_key={!r}, "
            "request_timeout_seconds={!r}, max_output_tokens={!r})"
        ).format(
            self.base_url,
            self.model,
            masked,
            self.request_timeout_seconds,
            self.max_output_tokens,
        )

    def validate_for_table_reconstruction(self) -> "LlmSettings":
        missing = [
            name
            for name, value in (
                ("LLM_BASE_URL", self.base_url),
                ("LLM_MODEL", self.model),
            )
            if value is None or not str(value).strip()
        ]
        if missing:
            raise SettingsError(
                "PDF 표 LLM 재구성 설정이 비어 있습니다: " + ", ".join(missing)
            )
        if self.request_timeout_seconds <= 0:
            raise SettingsError("LLM_REQUEST_TIMEOUT_SECONDS 값은 0보다 커야 합니다.")
        if self.max_output_tokens <= 0:
            raise SettingsError("LLM_MAX_OUTPUT_TOKENS 값은 0보다 커야 합니다.")
        return self


@dataclass(frozen=True)
class LoggingSettings:
    level: str = "INFO"
    log_dir: Path = PROJECT_ROOT / "logs"

    @classmethod
    def from_env(cls, env_file: str | Path | None = None, *, environ: Mapping[str, str] | None = None) -> "LoggingSettings":
        return get_settings(env_file=env_file, environ=environ).logging


@dataclass(frozen=True, repr=False)
class AppSettings:
    database: DatabaseSettings
    scheduler: SchedulerSettings
    pdf_load: PdfLoadSettings
    llm: LlmSettings
    logging: LoggingSettings

    @property
    def db(self) -> DatabaseSettings:
        """Compatibility alias for callers that prefer ``settings.db``."""
        return self.database

    def __repr__(self) -> str:
        return (
            "AppSettings(database={!r}, scheduler={!r}, pdf_load={!r}, "
            "llm={!r}, logging={!r})"
        ).format(
            self.database,
            self.scheduler,
            self.pdf_load,
            self.llm,
            self.logging,
        )


_CACHE: dict[tuple[object, ...], AppSettings] = {}


def get_settings(
    env_file: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    reload: bool = False,
) -> AppSettings:
    """Load and cache immutable settings for the current process."""
    path = _resolve_env_file(env_file)
    process = os.environ if environ is None else environ
    # The default process-wide cache is intentionally stable until ``reload``;
    # explicit ``environ`` mappings are keyed by content for deterministic tests.
    key = (str(path.resolve()), None if environ is None else tuple(sorted(process.items())))
    if reload:
        _CACHE.clear()
    if key in _CACHE:
        return _CACHE[key]
    values = _values(path, environ)

    def optional(name: str) -> str | None:
        raw = _get(values, name)
        text = _text(raw)
        return text or None

    db_port_raw = _get(values, "RS_DB_PORT")
    timeout_raw = _get(values, "RS_DB_CONNECT_TIMEOUT", 10)
    db = DatabaseSettings(
        host=optional("RS_DB_HOST"), port=parse_int(db_port_raw, variable_name="RS_DB_PORT") if db_port_raw not in (None, "") else None,
        user=optional("RS_DB_USER"), password=optional("RS_DB_PASSWORD"), dbname=optional("RS_DB_NAME"),
        connect_timeout=parse_int(timeout_raw, variable_name="RS_DB_CONNECT_TIMEOUT"), sslmode=optional("RS_DB_SSLMODE"),
    )
    misfire_raw = _get(values, "IPR_SCHEDULE_MISFIRE_GRACE", 3600)
    scheduler = SchedulerSettings(
        cron=_text(_get(values, "IPR_SCHEDULE_CRON", "0 3 * * *")),
        timezone=_text(_get(values, "IPR_SCHEDULE_TIMEZONE", "Asia/Seoul")) or "Asia/Seoul",
        config_path=_text(_get(values, "CRAWLER_CONFIG_PATH", "config.yaml")) or "config.yaml",
        period_mode=_text(_get(values, "IPR_SCHEDULE_PERIOD_MODE", "previous_day")) or "previous_day",
        target_month=optional("IPR_SCHEDULE_TARGET_MONTH"), start_date=optional("IPR_SCHEDULE_START_DATE"),
        end_date=optional("IPR_SCHEDULE_END_DATE"), companies=parse_csv(_get(values, "IPR_SCHEDULE_COMPANIES", ""), variable_name="IPR_SCHEDULE_COMPANIES"),
        misfire_grace_time=parse_int(misfire_raw, variable_name="IPR_SCHEDULE_MISFIRE_GRACE"),
    )
    pdf_raw = _get(values, "PDF_LOAD_HEADER_FOOTER_ENABLED", False)
    table_reconstruction_raw = _get(
        values, "PDF_LOAD_TABLE_RECONSTRUCTION_ENABLED", False
    )
    pdf = PdfLoadSettings(
        header_footer_enabled=(
            pdf_raw
            if isinstance(pdf_raw, bool)
            else parse_boolean(pdf_raw, variable_name="PDF_LOAD_HEADER_FOOTER_ENABLED")
        ),
        table_reconstruction_enabled=(
            table_reconstruction_raw
            if isinstance(table_reconstruction_raw, bool)
            else parse_boolean(
                table_reconstruction_raw,
                variable_name="PDF_LOAD_TABLE_RECONSTRUCTION_ENABLED",
            )
        ),
    )
    llm_timeout_raw = _get(values, "LLM_REQUEST_TIMEOUT_SECONDS", 120)
    llm_max_tokens_raw = _get(values, "LLM_MAX_OUTPUT_TOKENS", 8192)
    llm = LlmSettings(
        base_url=optional("LLM_BASE_URL"),
        model=optional("LLM_MODEL"),
        api_key=optional("LLM_API_KEY"),
        request_timeout_seconds=parse_float(
            llm_timeout_raw, variable_name="LLM_REQUEST_TIMEOUT_SECONDS"
        ),
        max_output_tokens=parse_int(
            llm_max_tokens_raw, variable_name="LLM_MAX_OUTPUT_TOKENS"
        ),
    )
    if pdf.table_reconstruction_enabled:
        llm.validate_for_table_reconstruction()
    log_dir_text = _text(_get(values, "IPR_LOG_DIR", PROJECT_ROOT / "logs"))
    log_dir = Path(log_dir_text or (PROJECT_ROOT / "logs"))
    if not log_dir.is_absolute():
        log_dir = PROJECT_ROOT / log_dir
    level = _text(_get(values, "LOG_LEVEL", "INFO")).upper() or "INFO"
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise SettingsError(f"LOG_LEVEL 값이 올바르지 않습니다: {level!r}")
    logging = LoggingSettings(level=level, log_dir=log_dir)
    result = AppSettings(
        database=db,
        scheduler=scheduler,
        pdf_load=pdf,
        llm=llm,
        logging=logging,
    )
    _CACHE[key] = result
    return result


__all__ = ["SettingsError", "DatabaseSettings", "SchedulerSettings", "PdfLoadSettings", "LlmSettings", "LoggingSettings", "AppSettings", "get_settings", "parse_boolean", "parse_bool", "parse_int", "parse_float", "parse_csv"]
