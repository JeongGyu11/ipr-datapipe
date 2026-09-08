"""파일 서버 보험사 단위 잠금 테스트."""

import multiprocessing
import json
from pathlib import Path

import pytest

import crawler.lock_service as lock_service
from crawler.lock_service import CompanyLock, LockHeldError, force_unlock, list_locks
from crawler.run_context import RunContext


def _hold_lock(path_text: str, ready, release) -> None:
    item = lock(Path(path_text), "DB", "CHILD")
    item.acquire()
    ready.set()
    release.wait(10)
    item.release()


def context(run_id: str) -> RunContext:
    return RunContext(
        run_id=run_id,
        computer_name="TEST-PC",
        process_id=100,
        started_at="2026-08-18T10:00:00",
        git_commit="abc123",
    )


def lock(path: Path, code: str, run_id: str) -> CompanyLock:
    return CompanyLock(
        path=path,
        company_code=code,
        company_name=f"{code}보험",
        scope_key="2026-07",
        context=context(run_id),
    )


def test_same_company_lock_allows_only_one_owner(tmp_path):
    path = tmp_path / "locks" / "DB.lock"
    first = lock(path, "DB", "RUN1")
    second = lock(path, "DB", "RUN2")
    first.acquire()
    try:
        with pytest.raises(LockHeldError) as exc:
            second.acquire()
        assert exc.value.owner["run_id"] == "RUN1"
        assert "operator" not in str(exc.value)
    finally:
        first.release()
    assert not path.exists()


def test_same_company_lock_is_exclusive_across_processes(tmp_path):
    path = tmp_path / "locks" / "DB.lock"
    process_context = multiprocessing.get_context("spawn")
    ready = process_context.Event()
    release = process_context.Event()
    process = process_context.Process(target=_hold_lock, args=(str(path), ready, release))
    process.start()
    try:
        assert ready.wait(10), "하위 프로세스가 잠금을 획득하지 못했습니다"
        with pytest.raises(LockHeldError):
            lock(path, "DB", "PARENT").acquire()
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
    assert process.exitcode == 0
    assert not path.exists()


def test_different_company_locks_can_coexist(tmp_path):
    db = lock(tmp_path / "locks" / "DB.lock", "DB", "RUN1")
    lotte = lock(tmp_path / "locks" / "LOTTE.lock", "LOTTE", "RUN2")
    with db, lotte:
        assert db.path.exists()
        assert lotte.path.exists()
        assert len(list_locks(tmp_path / "locks")) == 2
    assert not db.path.exists() and not lotte.path.exists()


def test_context_manager_releases_lock_on_exception(tmp_path):
    item = lock(tmp_path / "DB.lock", "DB", "RUN1")
    with pytest.raises(RuntimeError):
        with item:
            raise RuntimeError("boom")
    assert not item.path.exists()


def test_force_unlock_records_audit_event(tmp_path):
    item = lock(tmp_path / "locks" / "DB.lock", "DB", "RUN1")
    item.acquire()
    # 과거 lock JSON의 operator는 읽을 수 있지만 신규 감사 이벤트에는
    # 다시 기록하지 않는다.
    legacy = json.loads(item.path.read_text(encoding="utf-8"))
    legacy["operator"] = "기존사용자"
    item.path.write_text(json.dumps(legacy), encoding="utf-8")
    audit = tmp_path / "runs" / "ADMIN" / "lock_audit.jsonl"
    event = force_unlock(
        item.path,
        context=context("ADMIN"),
        audit_path=audit,
        display_path="99_운영/locks/DB.lock",
    )
    assert not item.path.exists()
    assert event["previous_owner"]["run_id"] == "RUN1"
    assert "operator" not in event["previous_owner"]
    assert isinstance(event["removed_by"], dict)
    assert event["lock_path"] == "99_운영/locks/DB.lock"
    assert "force_unlock" in audit.read_text(encoding="utf-8")


def test_failed_lock_write_does_not_leave_broken_lock(tmp_path, monkeypatch):
    item = lock(tmp_path / "locks" / "DB.lock", "DB", "RUN1")

    def fail_fsync(_):
        raise OSError("sync failed")

    monkeypatch.setattr(lock_service.os, "fsync", fail_fsync)
    with pytest.raises(OSError):
        item.acquire()
    assert not item.path.exists()
