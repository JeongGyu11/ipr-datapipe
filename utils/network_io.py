"""네트워크 파일 서버에서의 짧은 재시도와 내구화 보조 함수.

Windows SMB 경로에서는 ``fsync``가 ``EBADF``/``EINVAL``/``ENOTSUP``을
반환할 수 있다. 이 경우 파일 내용은 이미 ``flush`` 되었으므로 경고만
남기고 계속 진행한다. 그 밖의 일시적인 파일 서버 오류는 제한된 횟수만
재시도한다.
"""

from __future__ import annotations

import errno
import os
import stat
import threading
import time
from pathlib import Path
from typing import Callable, TypeVar

from utils.crawler_logger import get_logger


T = TypeVar("T")

# Windows/SMB에서 파일 핸들 fsync를 지원하지 않을 때 흔히 반환되는 값.
UNSUPPORTED_FSYNC_ERRNOS = frozenset(
    value
    for value in (
        # SMB 파일 핸들이 Windows CRT에서 유효하지 않은 핸들로 매핑될
        # 때 EBADF가 반환될 수 있다. UNC에서만 unsupported로 취급한다.
        getattr(errno, "EBADF", None),
        getattr(errno, "EINVAL", None),
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
        getattr(errno, "ENOSYS", None),
    )
    if value is not None
)

# 같은 회사의 JSONL append가 반복될 때 SMB의 미지원 fsync 경고가 매 행마다
# 네트워크 logger를 다시 쓰지 않도록 경로별로 한 번만 기록한다. set 접근은 여러
# 보험사 worker가 동시에 호출할 수 있으므로 Lock으로 보호한다.
_UNSUPPORTED_FSYNC_WARNED: set[str] = set()
_UNSUPPORTED_FSYNC_WARN_LOCK = threading.Lock()

# Linux 컨테이너에서 SMB bind mount는 ``/data``처럼 보이므로 Windows 네트워크
# 표기만으로는 네트워크 파일 시스템을 판별할 수 없다. PathService가 명시적
# SMB 모드에서 output root를 등록하면 이 목록 아래의 경로에도 동일한
# 재시도/내구화 정책을 적용한다.
_NETWORK_PATH_PREFIXES: tuple[str, ...] = ()


def _normalize_path_text(path: str | os.PathLike | None) -> str:
    text = str(path or "").replace("/", "\\")
    while len(text) > 1 and text.endswith("\\"):
        text = text[:-1]
    return text.casefold()


def configure_network_path(path: str | os.PathLike) -> None:
    """현재 프로세스의 단일 SMB 출력 루트를 등록한다."""

    global _NETWORK_PATH_PREFIXES
    normalized = _normalize_path_text(path)
    _NETWORK_PATH_PREFIXES = (normalized,) if normalized else ()


def reset_network_path() -> None:
    """테스트/프로세스 재초기화를 위해 SMB 루트 등록을 비운다."""

    global _NETWORK_PATH_PREFIXES
    _NETWORK_PATH_PREFIXES = ()


def is_network_path(path: str | os.PathLike | None) -> bool:
    """Windows 네트워크 또는 명시된 Linux SMB mount 경로인지 판정한다."""

    if path is None:
        return False
    text = _normalize_path_text(path)
    if text.startswith("\\\\"):
        return True
    return any(text == prefix or text.startswith(prefix + "\\") for prefix in _NETWORK_PATH_PREFIXES)


def strict_exists(path: str | os.PathLike) -> bool:
    """경로 존재 여부를 확인하되, ``Path.exists``의 오류 삼킴을 피한다.

    ``Path.exists()``는 일부 Windows/SMB ``OSError``를 ``False``로 바꿀 수
    있어 네트워크 장애를 파일 부재로 오판한다. ``stat``에서 실제 부재만
    ``False``로 처리하고 나머지 오류는 호출자(재시도 래퍼)에게 전달한다.
    """

    try:
        Path(path).stat()
    except FileNotFoundError:
        return False
    return True


def strict_is_dir(path: str | os.PathLike) -> bool:
    """디렉터리 여부를 검사하되 stat 오류를 부재로 삼키지 않는다."""

    try:
        return stat.S_ISDIR(Path(path).stat().st_mode)
    except FileNotFoundError:
        return False


def strict_is_file(path: str | os.PathLike) -> bool:
    """일반 파일 여부를 검사하되 stat 오류를 부재로 삼키지 않는다."""

    try:
        return stat.S_ISREG(Path(path).stat().st_mode)
    except FileNotFoundError:
        return False


def _path_from_handle(handle, path: str | os.PathLike | None) -> str:
    if path is not None:
        return str(path)
    try:
        return str(getattr(handle, "name", ""))
    except Exception:  # pragma: no cover - unusual file-like test doubles
        return ""


def retry_file_operation(
    operation: Callable[[], T],
    *,
    path: str | os.PathLike | None = None,
    attempts: int = 3,
    backoff: tuple[float, ...] = (0.1, 0.3),
    operation_name: str = "파일 작업",
) -> T:
    """네트워크 파일 작업을 제한적으로 재시도한다.

    로컬 경로는 기존 동작과 예외 타이밍을 보존하기 위해 한 번만 실행한다.
    네트워크 경로에서만 ``OSError``를 재시도하며, 마지막 예외는 호출자에게
    그대로 전달한다.
    """

    retryable = is_network_path(path)
    max_attempts = max(1, int(attempts)) if retryable else 1
    logger = get_logger()
    for attempt in range(max_attempts):
        try:
            return operation()
        except OSError as exc:
            if attempt + 1 >= max_attempts:
                raise
            delay = float(backoff[min(attempt, len(backoff) - 1)]) if backoff else 0.0
            logger.warning(
                "네트워크 파일 작업 실패(%s) 재시도 %d/%d, %.1f초 후: %s",
                operation_name,
                attempt + 1,
                max_attempts - 1,
                delay,
                exc,
            )
            if delay > 0:
                time.sleep(delay)
    raise AssertionError("unreachable")


def safe_fsync(
    handle,
    *,
    path: str | os.PathLike | None = None,
    attempts: int = 3,
) -> bool:
    """파일 핸들을 내구화한다.

    네트워크에서만 지원하지 않는 ``fsync`` 오류를 경고 후 무시하고 ``False``를
    반환한다. 로컬 경로 또는 그 밖의 오류는 재시도 후 예외를 전달한다.
    """

    resolved_path = _path_from_handle(handle, path)
    logger = get_logger()
    retryable = is_network_path(resolved_path)
    max_attempts = max(1, int(attempts)) if retryable else 1
    for attempt in range(max_attempts):
        try:
            os.fsync(handle.fileno())
            return True
        except OSError as exc:
            if retryable and getattr(exc, "errno", None) in UNSUPPORTED_FSYNC_ERRNOS:
                # SMB에서 지원되지 않는 fsync는 재시도해도 의미가 없고,
                # 앞선 flush 결과를 보존한 채 경고만 남긴다.
                warning_key = resolved_path or f"<handle:{id(handle)}>"
                with _UNSUPPORTED_FSYNC_WARN_LOCK:
                    first_warning = warning_key not in _UNSUPPORTED_FSYNC_WARNED
                    if first_warning:
                        _UNSUPPORTED_FSYNC_WARNED.add(warning_key)
                if first_warning:
                    logger.warning(
                        "네트워크 파일의 fsync를 지원하지 않아 flush 결과만 사용합니다: %s (%s)",
                        resolved_path,
                        exc,
                    )
                return False
            if attempt + 1 >= max_attempts:
                raise
            delay = (0.1, 0.3)[min(attempt, 1)] if retryable else 0.0
            logger.warning(
                "파일 fsync 실패 재시도 %d/%d, %.1f초 후: %s",
                attempt + 1,
                max_attempts - 1,
                delay,
                exc,
            )
            if delay > 0:
                time.sleep(delay)


def _rollback_append(path: Path, original_size: int, existed: bool) -> None:
    """부분 append를 원래 byte 경계로 되돌린다."""
    if not existed:
        safe_unlink(path)
        return
    with path.open("r+b") as fp:
        fp.truncate(original_size)
        fp.flush()
        safe_fsync(fp, path=path)


def durable_append_bytes(
    path: str | os.PathLike,
    payload: bytes,
    *,
    attempts: int = 3,
) -> None:
    """append를 수행하고 부분 write 실패 시 원래 길이로 rollback한다.

    호출부가 회사/run lock으로 단일 writer를 보장하는 JSONL 저널에 사용한다.
    네트워크에서만 bounded retry하며, rollback 자체가 실패하면 중복/손상 방지를
    위해 즉시 예외를 전파한다.
    """
    target = Path(path)
    retryable = is_network_path(target)
    max_attempts = max(1, int(attempts)) if retryable else 1
    for attempt in range(max_attempts):
        existed = retry_file_operation(
            lambda: strict_exists(target), path=target, operation_name="append 대상 확인"
        )
        original_size = retry_file_operation(
            lambda: target.stat().st_size, path=target, operation_name="append 크기 확인"
        ) if existed else 0
        append_started = False
        try:
            with target.open("ab") as fp:
                # open 자체가 공유 잠금 등으로 실패한 경우 파일 내용은
                # 바뀌지 않았으므로 rollback을 시도하면 안 된다. 실제 write
                # 호출에 진입한 뒤의 실패만 원래 크기로 되돌린다.
                append_started = True
                written = fp.write(payload)
                if written is not None and written != len(payload):
                    raise OSError(
                        f"append short write: {written}/{len(payload)} bytes"
                    )
                fp.flush()
                safe_fsync(fp, path=target)
            return
        except OSError:
            if append_started:
                try:
                    _rollback_append(target, original_size, existed)
                except OSError:
                    raise
            if attempt + 1 >= max_attempts:
                raise
            delay = (0.1, 0.3)[min(attempt, 1)] if retryable else 0.0
            if delay > 0:
                time.sleep(delay)


def durable_write_bytes(
    path: str | os.PathLike,
    payload: bytes,
    *,
    attempts: int = 3,
) -> None:
    """파일 전체를 임시 경로에 write/flush/fsync하며 bounded retry한다."""
    target = Path(path)
    retryable = is_network_path(target)
    max_attempts = max(1, int(attempts)) if retryable else 1
    for attempt in range(max_attempts):
        try:
            with target.open("wb") as fp:
                written = fp.write(payload)
                if written is not None and written != len(payload):
                    raise OSError(
                        f"write short write: {written}/{len(payload)} bytes"
                    )
                fp.flush()
                safe_fsync(fp, path=target)
            return
        except OSError:
            try:
                safe_unlink(target)
            except OSError:
                raise
            if attempt + 1 >= max_attempts:
                raise
            delay = (0.1, 0.3)[min(attempt, 1)] if retryable else 0.0
            if delay > 0:
                time.sleep(delay)


def safe_unlink(path: str | os.PathLike, *, attempts: int = 3) -> None:
    """네트워크 임시 파일 삭제를 제한적으로 재시도한다."""

    target = Path(path)

    def remove() -> None:
        target.unlink(missing_ok=True)

    retry_file_operation(remove, path=target, attempts=attempts, operation_name="임시 파일 삭제")


__all__ = [
    "UNSUPPORTED_FSYNC_ERRNOS",
    "is_network_path",
    "configure_network_path",
    "reset_network_path",
    "strict_exists",
    "strict_is_dir",
    "strict_is_file",
    "durable_append_bytes",
    "durable_write_bytes",
    "retry_file_operation",
    "safe_fsync",
    "safe_unlink",
]
