"""Backward-compatible facade for the application logger.

New code should import from :mod:`app.core.ipr_logger`; this module preserves the
historical ``setup_logging`` and ``ErrorRecorder`` APIs used by crawler code.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from app.core.ipr_logger import (
    LOGGER_NAME,
    DailyDateFileHandler,
    ResilientStreamHandler,
    configure_logging,
    get_logger as _get_logger,
    push_trace_id,
    reset_trace_id,
)

# Private names retained for callers/tests that imported the old implementation.
_ResilientFileHandler = DailyDateFileHandler


def setup_logging(log_dir: Path | None, verbose: bool = False, *, level: int | str | None = None):
    """Configure the crawler logger using the legacy call signature."""
    return configure_logging(SimpleNamespace(level=level, log_dir=log_dir), verbose=verbose)


def get_logger(name: str | None = None):
    return _get_logger(name)


class ErrorRecorder:
    """Append structured UTF-8 JSONL errors (legacy crawler contract)."""

    def __init__(self, path: Path | None):
        self.path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, **fields: object) -> None:
        if self.path is None:
            return
        payload = {"recorded_at": datetime.now().isoformat(timespec="seconds"), **fields}
        from utils.network_io import durable_append_bytes

        durable_append_bytes(self.path, (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))


__all__ = [
    "DailyDateFileHandler", "ErrorRecorder", "LOGGER_NAME", "ResilientStreamHandler",
    "configure_logging", "get_logger", "push_trace_id", "reset_trace_id", "setup_logging",
]
