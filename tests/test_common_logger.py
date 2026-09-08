"""Contract tests for the shared application logger."""

from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

from app.core.ipr_logger import DailyDateFileHandler, configure_logging, get_logger, push_trace_id, reset_trace_id


class _TTYBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def _clear() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_ipr_managed", False):
            root.removeHandler(handler)
            handler.close()
    if hasattr(root, "_ipr_logging_signature"):
        del root._ipr_logging_signature


def test_named_loggers_use_root_and_daily_file(tmp_path: Path, monkeypatch) -> None:
    _clear()
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    logger = configure_logging(SimpleNamespace(level="INFO", log_dir=tmp_path))
    get_logger("app.example").info("hello")
    get_logger("app.example").error("oops")
    for handler in logging.getLogger().handlers:
        handler.flush()
    files = list(tmp_path.glob("log_*.log"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "[INFO] [-] app.example - hello" in text
    assert "[ERROR] [-] app.example - oops" in text
    assert "oops" in err.getvalue() and "oops" not in out.getvalue()
    assert logger is get_logger()


def test_trace_id_push_reset_and_context_isolation(tmp_path: Path) -> None:
    _clear()
    configure_logging(SimpleNamespace(level="INFO", log_dir=tmp_path))
    logger = get_logger("trace.test")
    token = push_trace_id("abc")
    logger.info("inside")
    reset_trace_id(token)
    logger.info("outside")
    handler = next(h for h in logging.getLogger().handlers if isinstance(h, DailyDateFileHandler))
    handler.flush()
    text = next(tmp_path.glob("log_*.log")).read_text(encoding="utf-8")
    assert "[abc] trace.test - inside" in text
    assert "[-] trace.test - outside" in text


def test_trace_ids_do_not_leak_between_threads(tmp_path: Path) -> None:
    _clear()
    configure_logging(SimpleNamespace(level="INFO", log_dir=tmp_path))
    logger = get_logger("trace.concurrent")
    barrier = Barrier(2)

    def write(trace_id: str, message: str) -> None:
        token = push_trace_id(trace_id)
        try:
            barrier.wait(timeout=5)
            logger.info(message)
        finally:
            reset_trace_id(token)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(write, "trace-a", "message-a")
        second = executor.submit(write, "trace-b", "message-b")
        first.result(timeout=5)
        second.result(timeout=5)

    text = next(tmp_path.glob("log_*.log")).read_text(encoding="utf-8")
    assert "[trace-a] trace.concurrent - message-a" in text
    assert "[trace-b] trace.concurrent - message-b" in text


def test_console_color_is_tty_only_and_file_remains_plain(tmp_path: Path, monkeypatch) -> None:
    _clear()
    out, err = _TTYBuffer(), _TTYBuffer()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    configure_logging(SimpleNamespace(level="INFO", log_dir=tmp_path))

    get_logger("color.test").info("colored")

    console_text = out.getvalue()
    assert "\x1b[32m[INFO]\x1b[0m" in console_text
    assert not console_text.startswith("\x1b[")
    assert "color.test - colored\x1b[0m" not in console_text
    assert "\x1b[" not in next(tmp_path.glob("log_*.log")).read_text(encoding="utf-8")


def test_rollover_uses_record_timestamp_in_kst(tmp_path: Path) -> None:
    _clear()
    handler = DailyDateFileHandler(tmp_path)
    handler.setFormatter(logging.Formatter("%(message)s"))
    first = logging.LogRecord("x", logging.INFO, "", 0, "before", (), None)
    first.created = 1_756_738_799  # 2025-09-01 23:59:59 KST
    second = logging.LogRecord("x", logging.INFO, "", 0, "after", (), None)
    second.created = 1_756_738_800  # 2025-09-02 00:00:00 KST
    handler.emit(first)
    handler.emit(second)
    handler.close()
    assert "before" in (tmp_path / "log_2025-09-01.log").read_text()
    assert "after" in (tmp_path / "log_2025-09-02.log").read_text()
