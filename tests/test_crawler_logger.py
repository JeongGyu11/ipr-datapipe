"""Compatibility facade and resilience tests."""

from __future__ import annotations

import errno
import io
import json
import logging
from pathlib import Path

import pytest

from app.core.ipr_logger import DailyDateFileHandler
from utils.crawler_logger import ErrorRecorder, get_logger, setup_logging


@pytest.fixture(autouse=True)
def reset_logger() -> None:
    yield
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_ipr_managed", False):
            root.removeHandler(handler)
            handler.close()
    if hasattr(root, "_ipr_logging_signature"):
        del root._ipr_logging_signature


def test_utf8_daily_file_and_split_streams(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    logger = setup_logging(tmp_path, verbose=True)
    logger.info("한글 로그")
    logger.warning("경고 로그")
    for handler in logging.getLogger().handlers:
        handler.flush()
    text = next(tmp_path.glob("log_*.log")).read_text(encoding="utf-8")
    assert "한글 로그" in text and "경고 로그" in text
    assert "\x1b[" not in text
    assert "한글 로그" in out.getvalue() and "경고 로그" in err.getvalue()


def test_console_stream_failure_is_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        def isatty(self): return False
        def write(self, _value): raise BrokenPipeError
        def flush(self): raise BrokenPipeError

    healthy = io.StringIO()
    monkeypatch.setattr("sys.stdout", Broken())
    monkeypatch.setattr("sys.stderr", healthy)
    logger = setup_logging(None)
    logger.info("continue")
    assert "Logging error" not in healthy.getvalue()


def test_file_open_failure_keeps_console(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.core.ipr_logger.DailyDateFileHandler", lambda _path: (_ for _ in ()).throw(OSError("open failure")))
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    logger = setup_logging(tmp_path)
    logger.info("console only")
    assert "console only" in out.getvalue()
    assert len([h for h in logging.getLogger().handlers if getattr(h, "_ipr_managed", False)]) == 2


def test_repeated_setup_is_idempotent(tmp_path: Path) -> None:
    setup_logging(tmp_path)
    setup_logging(tmp_path)
    root = logging.getLogger()
    assert len([h for h in root.handlers if getattr(h, "_ipr_managed", False)]) == 3
    get_logger().info("once")
    for handler in root.handlers: handler.flush()
    assert next(tmp_path.glob("log_*.log")).read_text(encoding="utf-8").count("once") == 1


def test_error_recorder_and_named_logger(tmp_path: Path) -> None:
    logger = setup_logging(tmp_path)
    assert logger is get_logger() and logger.name == "crawler" and logger.propagate
    path = tmp_path / "errors.jsonl"
    ErrorRecorder(path).record(kind="test", message="한글 오류")
    assert json.loads(path.read_text(encoding="utf-8"))["message"] == "한글 오류"


def test_error_recorder_retries_transient_unc_append_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "errors.jsonl"
    original_open = Path.open
    attempts = 0

    def flaky_open(self: Path, mode: str = "r", *args: object, **kwargs: object):
        nonlocal attempts
        if self == path and mode == "ab":
            attempts += 1
            if attempts == 1:
                raise OSError(errno.EINVAL, "temporary UNC append failure")
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)
    monkeypatch.setattr("utils.network_io.is_network_path", lambda _path: True)
    monkeypatch.setattr("utils.network_io.time.sleep", lambda _delay: None)
    ErrorRecorder(path).record(kind="unc", message="일시적 SMB 오류")
    assert attempts == 2
