"""프로젝트 전역 설정 파일 경로 해석 규칙."""

from __future__ import annotations

import os
from pathlib import Path


# ``app/config_paths.py`` is one level below the repository root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def resolve_config_path(path: str | Path | None = None) -> Path:
    """Return an absolute config path using the project root as its base.

    When *path* is omitted, ``CRAWLER_CONFIG_PATH`` is honored and otherwise
    the repository's ``config.yaml`` is selected.  Relative paths are always
    interpreted relative to :data:`PROJECT_ROOT`, independent of the process
    working directory.
    """

    if path is None or not str(path).strip():
        configured = (os.getenv("CRAWLER_CONFIG_PATH") or "").strip()
        candidate = Path(configured) if configured else DEFAULT_CONFIG_PATH
    else:
        candidate = Path(path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


__all__ = ["PROJECT_ROOT", "DEFAULT_CONFIG_PATH", "resolve_config_path"]
