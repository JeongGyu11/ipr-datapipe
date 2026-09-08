"""실제 SMB mount에서 원자적 파일 작업과 lock을 검증한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

from crawler.config import load_config
from crawler.lock_service import CompanyLock
from crawler.path_service import PathService
from crawler.run_context import RunContext
from utils.network_io import (
    durable_append_bytes,
    durable_write_bytes,
    retry_file_operation,
    safe_unlink,
    strict_exists,
    strict_is_file,
)


LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    return parser


def _cleanup_smoke_artifacts(
    artifacts: tuple[Path, ...],
    smoke_root: Path,
    smoke_parent: Path,
    *,
    suppress_errors: bool,
) -> None:
    """스모크 산출물을 정리하되 본래 검증 오류를 가리지 않는다."""

    cleanup_errors: list[OSError] = []
    for path in artifacts:
        try:
            safe_unlink(path)
        except OSError as exc:
            cleanup_errors.append(exc)
    try:
        retry_file_operation(
            smoke_root.rmdir,
            path=smoke_root,
            operation_name="SMB smoke 디렉터리 정리",
        )
    except OSError as exc:
        cleanup_errors.append(exc)
    try:
        smoke_parent.rmdir()
    except OSError:
        # 다른 스모크 실행 디렉터리가 남아 있을 수 있으므로 부모 삭제 실패는
        # 정상적인 동시 실행 상황으로 취급한다.
        pass

    if not cleanup_errors:
        return
    message = f"SMB smoke 정리 실패: {cleanup_errors[0]}"
    if suppress_errors:
        LOGGER.warning(message)
        return
    raise RuntimeError(message) from cleanup_errors[0]


def run_smoke(config_path: str) -> dict[str, object]:
    config = load_config(config_path)
    scope_key = config.target_month or "storage_smoke"
    paths = PathService(
        base_path=config.base_path,
        root_folder=config.root_folder,
        target_month=scope_key,
        max_path_length=config.max_path_length,
        scope_key=scope_key,
        storage_kind=config.storage_kind,
        local_staging_override=config.local_staging_path,
        local_state_override=config.local_state_path,
    )
    paths.verify_base_path()
    context = RunContext.create()
    smoke_parent = paths.operations_root / "storage_smoke"
    smoke_root = smoke_parent / context.run_id
    retry_file_operation(
        lambda: smoke_root.mkdir(parents=True, exist_ok=False),
        path=smoke_root,
        operation_name="SMB smoke 디렉터리 생성",
    )

    source = smoke_root / "한글_원자쓰기.tmp"
    renamed = smoke_root / "한글_원자쓰기.done"
    journal = smoke_root / "append.jsonl"
    lock_path = smoke_root / "SMOKE.lock"
    payload = "보험 문서 SMB smoke test\n".encode("utf-8")
    expected_sha = hashlib.sha256(payload).hexdigest()
    try:
        durable_write_bytes(source, payload)
        actual_sha = hashlib.sha256(
            retry_file_operation(
                source.read_bytes,
                path=source,
                operation_name="SMB smoke 파일 읽기",
            )
        ).hexdigest()
        if actual_sha != expected_sha:
            raise RuntimeError("SMB smoke SHA-256 mismatch")
        retry_file_operation(
            lambda: os.replace(source, renamed),
            path=renamed,
            operation_name="SMB smoke 원자적 rename",
        )
        durable_append_bytes(journal, b'{"sequence":1}\n')
        durable_append_bytes(journal, b'{"sequence":2}\n')
        lines = retry_file_operation(
            lambda: journal.read_text(encoding="utf-8"),
            path=journal,
            operation_name="SMB smoke JSONL 읽기",
        ).splitlines()
        if [json.loads(line)["sequence"] for line in lines] != [1, 2]:
            raise RuntimeError("SMB smoke JSONL append mismatch")

        lock = CompanyLock(
            path=lock_path,
            company_code="SMOKE",
            company_name="SMB smoke",
            scope_key=scope_key,
            context=context,
        )
        with lock:
            if not retry_file_operation(
                lambda: strict_is_file(lock_path),
                path=lock_path,
                operation_name="SMB smoke lock 형식 확인",
            ):
                raise RuntimeError("SMB smoke lock was not created")
        if retry_file_operation(
            lambda: strict_exists(lock_path),
            path=lock_path,
            operation_name="SMB smoke lock 해제 확인",
        ):
            raise RuntimeError("SMB smoke lock was not released")
        return {
            "status": "ok",
            "sha256": expected_sha,
            "rename": True,
            "jsonl_records": 2,
            "lock_released": True,
        }
    finally:
        # finally 진입 시 활성 예외를 먼저 캡처한다. 정리 자체가 실패하더라도
        # SHA/rename/lock 검증에서 발생한 본래 오류가 가려지면 안 된다.
        original_error = sys.exception()
        _cleanup_smoke_artifacts(
            (source, renamed, journal, lock_path),
            smoke_root,
            smoke_parent,
            suppress_errors=original_error is not None,
        )


def main() -> int:
    args = build_parser().parse_args()
    print(json.dumps(run_smoke(args.config), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
