"""DB 장애 시 문서 결과를 재생할 최소 append-only outbox."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from utils.network_io import durable_append_bytes


class OutboxCorruptionError(RuntimeError):
    """재생을 중단해야 하는 손상/부분 JSONL 이벤트."""


class OutboxEventValidationError(ValueError):
    """DB outbox에 기록할 수 없는 operation/payload."""


ALLOWED_OPERATIONS = frozenset({"upsert_seen", "upsert_result", "update_status_rows"})
DEFAULT_COMPACT_DATA_BYTES = 8 * 1024 * 1024
DEFAULT_COMPACT_ACK_BYTES = 512 * 1024
# Prefix migration requires the outbox to be empty before cutover.  Therefore
# every event written or replayed under the v4 runtime must use the final key
# contract; accepting an old raw/64-character event after the DB CHECK changes
# would only create a permanent replay failure.
_DOCUMENT_KEY = re.compile(r"^DOC_[0-9A-Za-z]{10}$")
_PRODUCT_VERSION_KEY = re.compile(r"^PROD_VER_[0-9A-Za-z]{10}$")

# Windows byte-range locks are process/CRT-handle dependent.  A small
# in-process lock closes that gap for multiple crawler/replay threads while
# the byte-range lock below still serializes separate processes.
_MUTATION_LOCKS_GUARD = threading.Lock()
_MUTATION_LOCKS: dict[str, threading.RLock] = {}


def _process_mutation_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(str(path)))
    with _MUTATION_LOCKS_GUARD:
        lock = _MUTATION_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _MUTATION_LOCKS[key] = lock
        return lock


def is_transient_database_error(exc: BaseException) -> bool:
    """재연결 후 동일 이벤트를 안전하게 재생할 수 있는 DB 장애인지 판별한다.

    SQL 문법·제약조건·payload 오류는 outbox에 넣어도 자동 복구되지 않으므로
    연결 계열 예외만 transient로 본다. 원인 예외 체인도 함께 확인한다.
    """

    try:
        import psycopg

        transient_types = (psycopg.OperationalError, psycopg.InterfaceError)
    except ImportError:  # pragma: no cover - 런타임 의존성 누락은 readiness에서 차단
        transient_types = ()
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if transient_types and isinstance(current, transient_types):
            return True
        current = current.__cause__ or current.__context__
    return False


def validate_operation_event(event: dict[str, Any]) -> None:
    """운영 DB 이벤트의 operation과 최소 identity 계약을 검증한다."""

    if not isinstance(event, dict):
        raise OutboxEventValidationError("DB outbox 이벤트는 객체여야 합니다")
    operation = str(event.get("operation") or "")
    if operation not in ALLOWED_OPERATIONS:
        raise OutboxEventValidationError(f"허용되지 않은 DB outbox 작업입니다: {operation or '(없음)'}")
    payload = event.get("payload")
    rows = payload if operation == "update_status_rows" else [payload]
    if operation == "update_status_rows" and not isinstance(payload, list):
        raise OutboxEventValidationError("update_status_rows payload는 행 배열이어야 합니다")
    if operation != "update_status_rows" and not isinstance(payload, dict):
        raise OutboxEventValidationError(f"{operation} payload는 객체여야 합니다")
    if not rows:
        raise OutboxEventValidationError(f"{operation} payload가 비어 있습니다")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise OutboxEventValidationError(f"{operation} payload[{index}]는 객체여야 합니다")
        document_key = str(row.get("document_key") or "").strip()
        if not _DOCUMENT_KEY.fullmatch(document_key):
            raise OutboxEventValidationError(
                f"{operation} payload[{index}] document_key 형식이 잘못되었습니다"
            )
        product_version_key = str(row.get("product_version_key") or "").strip()
        if product_version_key and not _PRODUCT_VERSION_KEY.fullmatch(product_version_key):
            raise OutboxEventValidationError(
                f"{operation} payload[{index}] product_version_key 형식이 잘못되었습니다"
            )


class DatabaseOutbox:
    """manifest 스냅샷이 아닌 미반영 DB 이벤트만 보관한다.

    성공적으로 재생된 이벤트 ID는 별도 ACK 파일에 append하며, 데이터
    파일을 재작성하지 않아 장애 중에도 기록 유실 가능성을 줄인다.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.ack_path = self.path.with_suffix(self.path.suffix + ".acked")
        self.failure_path = self.path.with_suffix(self.path.suffix + ".failures")
        self.quarantine_path = self.path.with_suffix(self.path.suffix + ".quarantined")
        self.quarantine_audit_path = self.path.with_suffix(self.path.suffix + ".quarantine.jsonl")
        self.compaction_audit_path = self.path.with_suffix(self.path.suffix + ".compactions.jsonl")
        self.mutation_lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    @contextmanager
    def _mutation_lock(self, *, timeout_seconds: float = 30.0):
        """Serialize append/compact across processes without stale lock files."""

        process_lock = _process_mutation_lock(self.mutation_lock_path)
        timeout = max(0.0, float(timeout_seconds))
        if not process_lock.acquire(timeout=timeout):
            raise TimeoutError(f"DB outbox 변경 lock 시간 초과: {self.mutation_lock_path}")
        try:
            self.mutation_lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self.mutation_lock_path.open("a+b") as lock_file:
                lock_file.seek(0, os.SEEK_END)
                if lock_file.tell() == 0:
                    lock_file.write(b"0")
                    lock_file.flush()
                deadline = time.monotonic() + timeout
                while True:
                    try:
                        lock_file.seek(0)
                        if os.name == "nt":
                            import msvcrt

                            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                        else:  # pragma: no cover - 운영 환경은 Windows
                            import fcntl

                            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"DB outbox 변경 lock 시간 초과: {self.mutation_lock_path}")
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    lock_file.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    else:  # pragma: no cover - 운영 환경은 Windows
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            process_lock.release()

    def append(self, event: dict[str, Any], *, event_id: str | None = None) -> str:
        if "operation" in event or "payload" in event:
            validate_operation_event(event)
        identifier = event_id or uuid.uuid4().hex
        payload = {
            "event_id": identifier,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "event": event,
        }
        data = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self._mutation_lock():
            if event_id is not None:
                known = {str(item.get("event_id") or "") for _line, item in self._entries()}
                known |= self._acknowledged() | self._quarantined()
                if identifier in known:
                    raise OutboxEventValidationError(f"중복 DB outbox event_id입니다: {identifier}")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            durable_append_bytes(self.path, data)
        return identifier

    def pending(self) -> list[dict[str, Any]]:
        # Readers also take the mutation lock so they cannot observe a
        # partially written JSONL line while another process appends.
        with self._mutation_lock():
            return self._pending_unlocked()

    def _pending_unlocked(self) -> list[dict[str, Any]]:
        acknowledged = self._acknowledged() | self._quarantined()
        result: list[dict[str, Any]] = []
        for line_number, payload in self._entries():
            if payload.get("event_id") not in acknowledged:
                payload["_line_number"] = line_number
                result.append(payload)
        return result

    def _entries(self) -> list[tuple[int, dict[str, Any]]]:
        """Parse and validate every source event without applying ACK state."""

        if not self.path.exists():
            return []
        result: list[tuple[int, dict[str, Any]]] = []
        with self.path.open("r", encoding="utf-8") as fp:
            for line_number, line in enumerate(fp, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise OutboxCorruptionError(
                        f"outbox JSONL 손상: {self.path}:{line_number}"
                    ) from exc
                if (
                    not isinstance(payload, dict)
                    or not str(payload.get("event_id", "")).strip()
                    or not isinstance(payload.get("event"), dict)
                ):
                    raise OutboxCorruptionError(
                        f"outbox 이벤트 형식 오류: {self.path}:{line_number}"
                    )
                event = payload.get("event") or {}
                if "operation" in event or "payload" in event:
                    try:
                        validate_operation_event(event)
                    except OutboxEventValidationError as exc:
                        raise OutboxCorruptionError(
                            f"outbox DB 이벤트 형식 오류: {self.path}:{line_number}: {exc}"
                        ) from exc
                result.append((line_number, payload))
        return result

    def replay(self, handler: Callable[[dict[str, Any]], Any], *, max_events: int | None = None) -> dict[str, int]:
        # pending()에서 손상이 발견되면 예외를 호출부로 전파해 수집을
        # 계속하지 않는다. 조용히 건너뛰면 DB 상태 누락으로 보일 수 있다.
        pending = self.pending()
        attempted = succeeded = failed = 0
        for payload in pending[:max_events]:
            attempted += 1
            try:
                handler(payload.get("event") or {})
            except Exception as exc:
                failed += 1
                self._record_failure(str(payload.get("event_id", "")), exc)
                # 앞 이벤트가 실패한 뒤 뒤 이벤트를 먼저 ACK하면
                # 다음 실행의 DB 반영 순서가 역전될 수 있다. FIFO와
                # 보험사 단위 fail-closed 규칙을 위해 첫 실패에서 멈춘다.
                break
            self._ack(str(payload.get("event_id", "")))
            succeeded += 1
        if failed == 0:
            self.compact_if_needed()
        return {"attempted": attempted, "succeeded": succeeded, "failed": failed}

    def compact_if_needed(
        self,
        *,
        data_bytes: int = DEFAULT_COMPACT_DATA_BYTES,
        ack_bytes: int = DEFAULT_COMPACT_ACK_BYTES,
    ) -> dict[str, int] | None:
        """Bound replay cost after ACK logs grow beyond an operational threshold."""

        source_size = self.path.stat().st_size if self.path.exists() else 0
        ack_size = self.ack_path.stat().st_size if self.ack_path.exists() else 0
        if source_size < int(data_bytes) and ack_size < int(ack_bytes):
            return None
        return self.compact()

    def compact(self) -> dict[str, int]:
        """Atomically remove ACKed events while preserving pending/quarantined history.

        Callers must hold the same company-level lock used by collection/replay;
        otherwise an append racing the final replace could be lost. Quarantined
        source events remain in the main JSONL and their separate audit files.
        """

        with self._mutation_lock():
            acknowledged = self._acknowledged()
            entries = self._entries()
            retained = [payload for _line_number, payload in entries if payload["event_id"] not in acknowledged]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, raw_temp = tempfile.mkstemp(prefix=f"{self.path.name}.compact-", dir=self.path.parent)
            temp_path = Path(raw_temp)
            try:
                with os.fdopen(descriptor, "wb") as fp:
                    for payload in retained:
                        fp.write(
                            (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
                                "utf-8"
                            )
                        )
                    fp.flush()
                    os.fsync(fp.fileno())
                os.replace(temp_path, self.path)
                self.ack_path.unlink(missing_ok=True)
            finally:
                temp_path.unlink(missing_ok=True)
            result = {
                "before": len(entries),
                "removed": len(entries) - len(retained),
                "retained": len(retained),
            }
            durable_append_bytes(
                self.compaction_audit_path,
                (
                    json.dumps(
                        {**result, "compacted_at": datetime.now(timezone.utc).isoformat()},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8"),
            )
            return result

    def _acknowledged(self) -> set[str]:
        if not self.ack_path.exists():
            return set()
        with self.ack_path.open("r", encoding="utf-8") as fp:
            return {line.strip() for line in fp if line.strip()}

    def _ack(self, event_id: str) -> None:
        if not event_id:
            return
        with self._mutation_lock():
            self.ack_path.parent.mkdir(parents=True, exist_ok=True)
            durable_append_bytes(self.ack_path, (event_id + "\n").encode("utf-8"))

    def _quarantined(self) -> set[str]:
        if not self.quarantine_path.exists():
            return set()
        with self.quarantine_path.open("r", encoding="utf-8") as fp:
            return {line.strip() for line in fp if line.strip()}

    def _record_failure(self, event_id: str, exc: BaseException) -> None:
        payload = {
            "event_id": event_id,
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "failure_kind": "TRANSIENT" if is_transient_database_error(exc) else "PERMANENT",
            "exception_type": type(exc).__name__,
        }
        with self._mutation_lock():
            self.failure_path.parent.mkdir(parents=True, exist_ok=True)
            durable_append_bytes(
                self.failure_path,
                (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"),
            )

    def quarantine(self, event_id: str, *, reason: str, approved_by: str) -> None:
        """수동 승인된 영구 오류 이벤트를 재생 대기열에서 격리한다.

        데이터 누락을 자동으로 숨기지 않도록 자동 격리는 제공하지 않는다.
        원본 이벤트와 별도의 감사 레코드는 그대로 남는다.
        """

        event_id = str(event_id or "").strip()
        reason = str(reason or "").strip()
        approved_by = str(approved_by or "").strip()
        if not event_id or not reason or not approved_by:
            raise ValueError("event_id, reason, approved_by가 모두 필요합니다")
        with self._mutation_lock():
            candidates = {str(item.get("event_id") or "") for item in self._pending_unlocked()}
            if event_id not in candidates:
                raise KeyError(f"대기 중인 outbox 이벤트를 찾을 수 없습니다: {event_id}")
            audit = {
                "event_id": event_id,
                "quarantined_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "approved_by": approved_by,
            }
            self.quarantine_audit_path.parent.mkdir(parents=True, exist_ok=True)
            durable_append_bytes(
                self.quarantine_audit_path,
                (json.dumps(audit, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"),
            )
            durable_append_bytes(self.quarantine_path, (event_id + "\n").encode("utf-8"))
