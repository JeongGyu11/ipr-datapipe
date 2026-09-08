"""공유 파일 서버에서 보험사 단위 중복 실행을 막는 배타적 잠금."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from crawler.run_context import RunContext
from utils.network_io import (
    durable_append_bytes,
    retry_file_operation,
    safe_fsync,
    safe_unlink,
    strict_exists,
)


class LockHeldError(RuntimeError):
    def __init__(self, path: Path, owner: dict):
        self.path = path
        self.owner = owner
        run_id = owner.get("run_id") or "알 수 없음"
        computer = owner.get("computer_name") or "알 수 없음"
        process_id = owner.get("process_id") or "알 수 없음"
        started = owner.get("started_at") or "알 수 없음"
        super().__init__(
            "다른 프로세스가 실행 중입니다 "
            f"(run_id={run_id}, PC={computer}, PID={process_id}, 시작={started})"
        )


@dataclass
class CompanyLock:
    path: Path
    company_code: str
    company_name: str
    scope_key: str
    context: RunContext
    acquired: bool = False
    period_start: str = ""
    period_end: str = ""

    def acquire(self) -> None:
        retry_file_operation(
            lambda: self.path.parent.mkdir(parents=True, exist_ok=True),
            path=self.path.parent,
            operation_name="회사 lock 디렉터리 생성",
        )
        payload = {
            **self.context.to_dict(),
            "company_code": self.company_code,
            "company_name": self.company_name,
            "scope_key": self.scope_key,
            "period_start": self.period_start,
            "period_end": self.period_end,
        }
        def _create() -> None:
            created = False
            try:
                fp = open(self.path, "x", encoding="utf-8")
                created = True
                with fp:
                    json.dump(payload, fp, ensure_ascii=False, indent=2)
                    fp.flush()
                    safe_fsync(fp, path=self.path)
            except FileExistsError as exc:
                raise LockHeldError(self.path, read_lock(self.path)) from exc
            except Exception:
                if created:
                    safe_unlink(self.path)
                raise

        retry_file_operation(
            _create,
            path=self.path,
            operation_name="회사 lock 생성",
        )
        self.acquired = True

    def release(self) -> None:
        if not self.acquired:
            return
        owner = read_lock(self.path)
        if owner.get("run_id") == self.context.run_id:
            safe_unlink(self.path)
        self.acquired = False

    def __enter__(self) -> "CompanyLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def read_lock(path: Path) -> dict:
    try:
        def _read() -> dict:
            with open(path, encoding="utf-8") as fp:
                value = json.load(fp)
            return value if isinstance(value, dict) else {}
        data = retry_file_operation(_read, path=path, operation_name="lock 읽기")
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {"unreadable": True}


def list_locks(locks_root: Path) -> list[dict]:
    if not retry_file_operation(
        lambda: strict_exists(locks_root),
        path=locks_root,
        operation_name="lock 루트 존재 확인",
    ):
        return []
    result = []
    paths = retry_file_operation(lambda: sorted(locks_root.glob("*.lock")), path=locks_root, operation_name="lock 목록 조회")
    for path in paths:
        result.append({"path": str(path), **read_lock(path)})
    return result


def force_unlock(
    path: Path,
    *,
    context: RunContext | None = None,
    audit_path: Path | None = None,
    display_path: str | None = None,
) -> dict:
    if not retry_file_operation(
        lambda: strict_exists(path),
        path=path,
        operation_name="lock 파일 존재 확인",
    ):
        raise FileNotFoundError(f"잠금 파일이 없습니다: {path}")
    owner = read_lock(path)
    safe_unlink(path)
    actor = context.to_dict() if context is not None else {
        "run_id": "",
        "computer_name": "",
        "process_id": os.getpid(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": "",
    }
    # 과거 lock JSON을 감사 이력에 그대로 복사하면 operator가 다시
    # 유출될 수 있으므로, 호환 읽기용 원본에서도 개인 식별자를 제거한다.
    previous_owner = {
        key: value for key, value in owner.items() if key != "operator"
    }
    event = {
        "action": "force_unlock",
        "removed_at": datetime.now().isoformat(timespec="seconds"),
        "removed_by": actor,
        # Audit records are part of the public run metadata.  Keep them
        # portable and prevent leaking UNC/drive/host-specific paths.
        "lock_path": display_path or str(path),
        "previous_owner": previous_owner,
    }
    if audit_path is not None:
        retry_file_operation(
            lambda: audit_path.parent.mkdir(parents=True, exist_ok=True),
            path=audit_path.parent,
            operation_name="lock audit 디렉터리 생성",
        )
        durable_append_bytes(
            audit_path,
            (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"),
        )
    return event
