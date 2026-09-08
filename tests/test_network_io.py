"""UNC 파일 서버 I/O 보조 함수와 로컬 staging 경로 회귀 테스트."""

import errno
from pathlib import Path

import pytest

import utils.network_io as unc_io
import crawler.path_service as path_module
import crawler.validators as validators
from crawler.path_service import PathService


class _Handle:
    name = r"\\Fileserver\share\checkpoint.jsonl"

    def fileno(self):
        return 99


def test_safe_fsync_ignores_unsupported_unc_error(monkeypatch):
    calls = 0

    def unsupported(_):
        nonlocal calls
        calls += 1
        raise OSError(errno.EINVAL, "Invalid argument")

    monkeypatch.setattr(unc_io.os, "fsync", unsupported)
    assert unc_io.safe_fsync(_Handle()) is False
    assert calls == 1


def test_safe_fsync_ignores_ebadf_for_unc_path(monkeypatch):
    calls = 0

    def bad_handle(_):
        nonlocal calls
        calls += 1
        raise OSError(errno.EBADF, "Bad file descriptor")

    monkeypatch.setattr(unc_io.os, "fsync", bad_handle)
    assert unc_io.safe_fsync(_Handle()) is False
    assert calls == 1


def test_safe_fsync_propagates_ebadf_for_local_path(monkeypatch, tmp_path):
    def bad_handle(_):
        raise OSError(errno.EBADF, "Bad file descriptor")

    monkeypatch.setattr(unc_io.os, "fsync", bad_handle)
    with pytest.raises(OSError, match="Bad file descriptor"):
        unc_io.safe_fsync(_Handle(), path=tmp_path / "local.jsonl")


def test_safe_fsync_warns_once_per_unc_path(monkeypatch):
    class Handle:
        def __init__(self, name):
            self.name = name

        def fileno(self):
            return 99

    warnings = []

    class Logger:
        def warning(self, *args):
            warnings.append(args)

    def unsupported(_):
        raise OSError(errno.EINVAL, "Invalid argument")

    unc_io._UNSUPPORTED_FSYNC_WARNED.clear()
    monkeypatch.setattr(unc_io.os, "fsync", unsupported)
    monkeypatch.setattr(unc_io, "get_logger", lambda: Logger())
    same_path = Handle(r"\\Fileserver\share\same.jsonl")
    other_path = Handle(r"\\Fileserver\share\other.jsonl")
    assert unc_io.safe_fsync(same_path) is False
    assert unc_io.safe_fsync(same_path) is False
    assert unc_io.safe_fsync(other_path) is False
    assert len(warnings) == 2


def test_safe_fsync_propagates_unsupported_error_for_local_path(monkeypatch, tmp_path):
    def unsupported(_):
        raise OSError(errno.EINVAL, "Invalid argument")

    monkeypatch.setattr(unc_io.os, "fsync", unsupported)
    with pytest.raises(OSError):
        unc_io.safe_fsync(_Handle(), path=tmp_path / "local.jsonl")


def test_retry_file_operation_retries_unc_only(monkeypatch):
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise OSError("transient")
        return "ok"

    monkeypatch.setattr(unc_io.time, "sleep", lambda _: None)
    assert unc_io.retry_file_operation(
        operation,
        path=r"\\Fileserver\share\file.pdf",
        attempts=3,
    ) == "ok"
    assert calls == 3


def test_strict_exists_retries_stat_error_and_does_not_swallow(monkeypatch, tmp_path):
    path = tmp_path / "present.jsonl"
    path.write_bytes(b"x")
    original_stat = Path.stat
    calls = 0

    def flaky_stat(self, *args, **kwargs):
        nonlocal calls
        if self == path and calls == 0:
            calls += 1
            raise OSError(errno.EINVAL, "network hiccup")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", flaky_stat)
    monkeypatch.setattr(unc_io, "is_network_path", lambda _: True)
    monkeypatch.setattr(unc_io.time, "sleep", lambda _: None)
    assert unc_io.retry_file_operation(
        lambda: unc_io.strict_exists(path), path=path, backoff=()
    ) is True
    assert calls == 1


def test_strict_exists_raises_persistent_stat_error(monkeypatch, tmp_path):
    path = tmp_path / "present.jsonl"

    # Keep a direct reference to avoid recursively invoking the patched method
    # for unrelated paths.
    original_stat = Path.stat
    def broken_stat(self, *args, **kwargs):
        if self == path:
            raise OSError(errno.EINVAL, "persistent network error")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", broken_stat)
    monkeypatch.setattr(unc_io, "is_network_path", lambda _: True)
    monkeypatch.setattr(unc_io.time, "sleep", lambda _: None)
    with pytest.raises(OSError, match="persistent network error"):
        unc_io.retry_file_operation(
            lambda: unc_io.strict_exists(path), path=path, backoff=()
        )


def test_durable_append_short_write_is_rolled_back_and_retried(tmp_path, monkeypatch):
    path = tmp_path / "journal.jsonl"
    path.write_bytes(b"old\n")
    original_open = Path.open
    failures = 0

    class ShortWriter:
        def __init__(self, real):
            self.real = real

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.real.close()

        def write(self, data):
            nonlocal failures
            if failures == 0:
                failures += 1
                self.real.write(data[:2])
                return 2
            return self.real.write(data)

        def flush(self):
            return self.real.flush()

        def fileno(self):
            return self.real.fileno()

    def flaky_open(self, mode="r", *args, **kwargs):
        real = original_open(self, mode, *args, **kwargs)
        if self == path and mode == "ab":
            return ShortWriter(real)
        return real

    monkeypatch.setattr(Path, "open", flaky_open)
    monkeypatch.setattr(unc_io, "is_network_path", lambda _: True)
    monkeypatch.setattr(unc_io.time, "sleep", lambda _: None)
    unc_io.durable_append_bytes(path, b"new\n")
    assert path.read_bytes() == b"old\nnew\n"
    assert failures == 1


def test_validate_saved_file_propagates_unc_stat_error_for_retry(monkeypatch, tmp_path):
    path = tmp_path / "document.pdf"
    path.write_bytes(b"%PDF-1.7\n")
    expected_size = path.stat().st_size
    original_stat = Path.stat

    def broken_stat(self, *args, **kwargs):
        if self == path:
            raise OSError(errno.EINVAL, "temporary UNC stat error")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", broken_stat)
    with pytest.raises(OSError, match="temporary UNC stat error"):
        validators.validate_saved_file(path, expected_size, ".pdf")


def test_durable_append_rolls_back_partial_write_before_retry(tmp_path, monkeypatch):
    path = tmp_path / "journal.jsonl"
    path.write_bytes(b'{"key":"old"}\n')
    original_open = Path.open
    failures = 0

    class PartialWriter:
        def __init__(self, real):
            self.real = real

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.real.close()

        def write(self, data):
            self.real.write(data[:3])
            self.real.flush()
            raise OSError("transient write")

        def flush(self):
            return self.real.flush()

        def fileno(self):
            return self.real.fileno()

    def flaky_open(self, mode="r", *args, **kwargs):
        nonlocal failures
        real = original_open(self, mode, *args, **kwargs)
        if self == path and mode == "ab" and failures == 0:
            failures += 1
            return PartialWriter(real)
        return real

    monkeypatch.setattr(Path, "open", flaky_open)
    monkeypatch.setattr(unc_io, "is_network_path", lambda _: True)
    monkeypatch.setattr(unc_io.time, "sleep", lambda _: None)
    unc_io.durable_append_bytes(path, b'{"key":"new"}\n')

    assert path.read_bytes() == b'{"key":"old"}\n{"key":"new"}\n'
    assert failures == 1


def test_durable_append_retries_open_failure_without_rollback(tmp_path, monkeypatch):
    path = tmp_path / "journal.jsonl"
    path.write_bytes(b'{"key":"old"}\n')
    original_open = Path.open
    append_attempts = 0
    rollback_attempts = 0

    def flaky_open(self, mode="r", *args, **kwargs):
        nonlocal append_attempts, rollback_attempts
        if self == path and mode == "ab":
            append_attempts += 1
            if append_attempts == 1:
                raise PermissionError(errno.EACCES, "temporary share lock")
        if self == path and mode == "r+b":
            rollback_attempts += 1
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)
    monkeypatch.setattr(unc_io, "is_network_path", lambda _: True)
    monkeypatch.setattr(unc_io.time, "sleep", lambda _: None)

    unc_io.durable_append_bytes(path, b'{"key":"new"}\n')

    assert path.read_bytes() == b'{"key":"old"}\n{"key":"new"}\n'
    assert append_attempts == 2
    assert rollback_attempts == 0


def test_durable_append_rollback_failure_is_fatal(tmp_path, monkeypatch):
    path = tmp_path / "journal.jsonl"
    path.write_bytes(b'{"key":"old"}\n')
    original_open = Path.open

    class PartialWriter:
        def __init__(self, real):
            self.real = real

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.real.close()

        def write(self, data):
            self.real.write(data[:2])
            self.real.flush()
            raise OSError("transient write")

        def flush(self):
            return self.real.flush()

        def fileno(self):
            return self.real.fileno()

    def broken_open(self, mode="r", *args, **kwargs):
        real = original_open(self, mode, *args, **kwargs)
        if self == path and mode == "ab":
            return PartialWriter(real)
        if self == path and mode == "r+b":
            real.close()
            raise OSError("rollback failed")
        return real

    monkeypatch.setattr(Path, "open", broken_open)
    monkeypatch.setattr(unc_io, "is_network_path", lambda _: True)
    with pytest.raises(OSError, match="rollback failed"):
        unc_io.durable_append_bytes(path, b'{"key":"new"}\n')


def test_local_staging_is_separate_for_unc_output(tmp_path):
    service = PathService(
        base_path=r"\\Fileserver\share\output",
        root_folder="상품공시실문서",
        target_month="2026-08",
    )
    assert service.is_network_output
    assert str(service.server_upload_staging_dir("RUN", "DB")).startswith(r"\\Fileserver")
    assert not str(service.download_staging_dir("RUN", "DB")).startswith(r"\\Fileserver")


def test_local_output_keeps_staging_under_operations_root(tmp_path):
    service = PathService(
        base_path=str(tmp_path),
        root_folder="상품공시실문서",
        target_month="2026-08",
    )
    assert not service.is_network_output


def test_unc_staging_falls_back_when_temp_is_unc(monkeypatch, tmp_path):
    service = PathService(
        base_path=r"\\Fileserver\share\output",
        root_folder="상품공시실문서",
        target_month="2026-08",
    )
    monkeypatch.setattr(path_module.tempfile, "gettempdir", lambda: r"\\Fileserver\share\temp")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    assert not unc_io.is_network_path(service.local_staging_root)
