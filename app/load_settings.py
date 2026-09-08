"""PDF Load 전용 환경 설정.

이 모듈은 PDF Load가 사용하는 환경변수만 해석한다. ``.env``를 현재
프로세스에 주입하지 않고 읽기만 하므로, 다른 애플리케이션 설정이나
테스트 프로세스의 환경을 변경하지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping
from app.config_paths import PROJECT_ROOT
from app.core.settings import PdfLoadSettings as _PdfLoadSettings
from app.core.settings import SettingsError, get_settings, parse_boolean as _parse_boolean


PDF_LOAD_HEADER_FOOTER_ENV = "PDF_LOAD_HEADER_FOOTER_ENABLED"
PDF_LOAD_TABLE_RECONSTRUCTION_ENV = "PDF_LOAD_TABLE_RECONSTRUCTION_ENABLED"
DEFAULT_HEADER_FOOTER_ENABLED = False
DEFAULT_TABLE_RECONSTRUCTION_ENABLED = False
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

_TRUE_VALUES = frozenset({"true", "1", "on", "yes"})
_FALSE_VALUES = frozenset({"false", "0", "off", "no"})


class PdfLoadSettingsError(SettingsError):
    """PDF Load 환경 설정이 유효하지 않을 때 발생하는 오류."""


def parse_boolean(value: object, *, variable_name: str = PDF_LOAD_HEADER_FOOTER_ENV) -> bool:
    """Parse a strict, case-insensitive boolean environment value.

    Whitespace around a value is ignored. Empty values and arbitrary strings
    are rejected rather than silently falling back to the default, because a
    typo in a deployment environment should be visible before parsing starts.
    """

    try:
        return _parse_boolean(value, variable_name=variable_name)
    except SettingsError as exc:
        raise PdfLoadSettingsError(
            f"{exc}. 허용값: true, false, 1, 0, on, off, yes, no"
        ) from None


class PdfLoadSettings(_PdfLoadSettings):
    """PDF Load 실행에 필요한 전용 설정."""

    header_footer_enabled: bool = DEFAULT_HEADER_FOOTER_ENABLED
    table_reconstruction_enabled: bool = DEFAULT_TABLE_RECONSTRUCTION_ENABLED

    @classmethod
    def from_env(
        cls,
        env_file: str | Path | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "PdfLoadSettings":
        """Load settings with OS environment taking precedence over ``.env``.

        ``env_file`` defaults to the repository root's ``.env``. A missing
        file is allowed because all PDF Load settings have safe defaults. The
        *environ* argument is intended for deterministic callers/tests; when
        omitted, the live :data:`os.environ` mapping is used.
        """

        try:
            settings = get_settings(env_file=env_file, environ=environ).pdf_load
            return cls(
                header_footer_enabled=settings.header_footer_enabled,
                table_reconstruction_enabled=settings.table_reconstruction_enabled,
            )
        except SettingsError as exc:
            raise PdfLoadSettingsError(str(exc)) from None


__all__ = [
    "DEFAULT_ENV_FILE",
    "DEFAULT_HEADER_FOOTER_ENABLED",
    "DEFAULT_TABLE_RECONSTRUCTION_ENABLED",
    "PDF_LOAD_HEADER_FOOTER_ENV",
    "PDF_LOAD_TABLE_RECONSTRUCTION_ENV",
    "PdfLoadSettings",
    "PdfLoadSettingsError",
    "parse_boolean",
]
