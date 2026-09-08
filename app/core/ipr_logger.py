"""Application-wide logging configuration.

The public surface is deliberately small: :func:`configure_logging`,
:func:`get_logger`, and trace-id context helpers.  Handlers are attached to
the process root so framework and application loggers share one stream.
"""

from __future__ import annotations

import logging
import re
import sys
from contextvars import ContextVar, Token
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO
from zoneinfo import ZoneInfo

LOGGER_NAME = "crawler"
try:
    KST = ZoneInfo("Asia/Seoul")
except Exception:  # tzdata can be unavailable in minimal/locked runtimes
    KST = timezone(timedelta(hours=9), name="KST")
_TRACE_ID: ContextVar[str] = ContextVar("trace_id", default="-")
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def push_trace_id(trace_id: str | None) -> Token[str]:
    """Set the trace id for the current context and return a reset token."""

    return _TRACE_ID.set(str(trace_id) if trace_id else "-")


def reset_trace_id(token: Token[str]) -> None:
    """Restore the trace id represented by *token*."""

    _TRACE_ID.reset(token)


def _kst_now() -> datetime:
    return datetime.now(KST)


def _resolve_level(value: Any, *, verbose: bool = False) -> int:
    if isinstance(value, int) and value in _LEVELS.values():
        return value
    name = str(value or "INFO").strip().upper()
    level = _LEVELS.get(name, logging.INFO)
    return logging.DEBUG if verbose else level


class _TraceFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _TRACE_ID.get()
        return True


class _BelowWarningFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.WARNING


class ResilientStreamHandler(logging.StreamHandler):
    """A stream handler that disables itself after a broken/closed stream."""

    def __init__(self, stream: TextIO) -> None:
        super().__init__(stream)
        self._failed = False

    def emit(self, record: logging.LogRecord) -> None:
        if self._failed:
            return
        try:
            message = self.format(record)
            if self.stream is None:
                self._failed = True
                return
            self.stream.write(message + self.terminator)
            self.flush()
        except Exception:
            self._failed = True


class _TTYFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[35m",
    }
    RESET = "\033[0m"

    def __init__(self, stream: TextIO) -> None:
        super().__init__("%(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s - %(message)s", "%Y-%m-%d %H:%M:%S")
        try:
            self._use_color = bool(getattr(stream, "isatty", lambda: False)())
        except Exception:
            self._use_color = False

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        value = datetime.fromtimestamp(record.created, KST)
        return value.strftime(datefmt or "%Y-%m-%d %H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        color = self.COLORS.get(record.levelno)
        if not self._use_color or not color:
            return text
        level_token = f"[{record.levelname}]"
        colored_level_token = f"{color}{level_token}{self.RESET}"
        return text.replace(level_token, colored_level_token, 1)


class _PlainFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s - %(message)s", "%Y-%m-%d %H:%M:%S")

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        value = datetime.fromtimestamp(record.created, KST)
        return value.strftime(datefmt or "%Y-%m-%d %H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        return _ANSI_RE.sub("", super().format(record))


class DailyDateFileHandler(logging.Handler):
    """UTF-8 file handler writing one ``log_YYYY-MM-DD.log`` per KST day."""

    terminator = "\n"

    def __init__(self, log_dir: Path) -> None:
        super().__init__()
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._stream: TextIO | None = None
        self._date: date | None = None
        self._failed = False
        self._open_for(self._current_date())

    def _current_date(self) -> date:
        return _kst_now().date()

    def _open_for(self, day: date) -> None:
        if self._stream is not None:
            try:
                self._stream.flush()
                self._stream.close()
            except Exception:
                pass
        path = self.log_dir / f"log_{day.isoformat()}.log"
        self._stream = path.open("a", encoding="utf-8", newline="")
        self._date = day
        self._failed = False

    @property
    def stream(self) -> TextIO | None:
        return self._stream

    def emit(self, record: logging.LogRecord) -> None:
        if self._failed:
            return
        try:
            # Derive the target day from the event timestamp.  Besides being
            # correct for KST, this makes rollover deterministic for queued or
            # test-created records that cross midnight.
            day = datetime.fromtimestamp(record.created, KST).date()
            if self._stream is None or day != self._date:
                self._open_for(day)
            assert self._stream is not None
            self._stream.write(self.format(record) + self.terminator)
            self._stream.flush()
        except Exception:
            self._failed = True

    def flush(self) -> None:
        try:
            if self._stream is not None:
                self._stream.flush()
        except Exception:
            self._failed = True

    def close(self) -> None:
        try:
            self.flush()
            if self._stream is not None:
                self._stream.close()
        except Exception:
            pass
        self._stream = None
        super().close()


def _safe_reconfigure(stream: TextIO) -> None:
    fn = getattr(stream, "reconfigure", None)
    if callable(fn):
        try:
            fn(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _close_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


def _close_managed_root_handlers(root: logging.Logger) -> None:
    """Remove handlers installed by this module while preserving user ones."""
    for handler in list(root.handlers):
        if getattr(handler, "_ipr_managed", False):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a standard named logger configured to propagate to the root."""

    logger = logging.getLogger(name or LOGGER_NAME)
    if logger.name != "root":
        logger.propagate = True
    return logger


def configure_logging(logging_settings: Any, verbose: bool = False) -> logging.Logger:
    """Configure console and daily-file handlers from a settings object.

    ``logging_settings`` is expected to expose ``level`` and ``log_dir``;
    ``log_dir`` may be ``None`` to disable file output.
    """

    configured_level = getattr(logging_settings, "level", None)
    log_dir = getattr(logging_settings, "log_dir", None)
    threshold = _resolve_level(configured_level, verbose=verbose)
    root = logging.getLogger()
    logger = logging.getLogger(LOGGER_NAME)
    logger.propagate = True
    signature = (
        threshold,
        str(Path(log_dir)) if log_dir is not None else None,
        id(sys.stdout),
        id(sys.stderr),
    )
    if getattr(root, "_ipr_logging_signature", None) == signature and any(
        getattr(h, "_ipr_managed", False) for h in root.handlers
    ):
        return logger
    _close_managed_root_handlers(root)
    # Remove handlers left by older versions of the compatibility facade.
    _close_handlers(logger)
    root.setLevel(threshold)
    _safe_reconfigure(sys.stdout)
    _safe_reconfigure(sys.stderr)

    stdout_handler = ResilientStreamHandler(sys.stdout)
    stdout_handler.setLevel(threshold)
    stdout_handler.addFilter(_BelowWarningFilter())
    stdout_handler.addFilter(_TraceFilter())
    stdout_handler.setFormatter(_TTYFormatter(sys.stdout))
    stdout_handler._ipr_managed = True  # type: ignore[attr-defined]

    stderr_handler = ResilientStreamHandler(sys.stderr)
    stderr_handler.setLevel(max(threshold, logging.WARNING))
    stderr_handler.addFilter(_TraceFilter())
    stderr_handler.setFormatter(_TTYFormatter(sys.stderr))
    stderr_handler._ipr_managed = True  # type: ignore[attr-defined]
    root.addHandler(stdout_handler)
    root.addHandler(stderr_handler)

    if log_dir is not None:
        try:
            file_handler = DailyDateFileHandler(Path(log_dir))
        except (OSError, ValueError) as exc:
            logger.warning("파일 로그를 시작할 수 없어 콘솔 로그만 사용합니다: %s (%s)", Path(log_dir), exc)
        else:
            file_handler.setLevel(threshold)
            file_handler.addFilter(_TraceFilter())
            file_handler.setFormatter(_PlainFormatter())
            file_handler._ipr_managed = True  # type: ignore[attr-defined]
            root.addHandler(file_handler)
    root._ipr_logging_signature = signature  # type: ignore[attr-defined]
    for library_name in ("httpx", "httpcore", "uvicorn", "uvicorn.error", "uvicorn.access"):
        library_logger = logging.getLogger(library_name)
        _close_handlers(library_logger)
        library_logger.propagate = True
        library_logger.setLevel(
            logging.WARNING if library_name in {"httpx", "httpcore"} else max(threshold, logging.INFO)
        )
    return logger


__all__ = [
    "DailyDateFileHandler",
    "LOGGER_NAME",
    "ResilientStreamHandler",
    "configure_logging",
    "get_logger",
    "push_trace_id",
    "reset_trace_id",
]
