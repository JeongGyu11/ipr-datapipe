from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

import pytest

from app.application.collection import (
    AdvisoryLockUnavailable,
    CollectionApplication,
    CollectionRequest,
    CollectionResult,
)
from crawler.config import AppConfig
from crawler.plan_service import PlanItem
from crawler.run_context import RunContext


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        target_month="2026-08",
        base_path=str(tmp_path),
        root_folder="output",
        crawler={},
        download={},
        document_types={},
        document_exclude_keywords=[],
        date_selection_mode="new_or_revised",
    )


def _context(_root: Path) -> RunContext:
    return RunContext("20260826_030000_run1", "TEST-PC", 123, "2026-08-26T03:00:00", "abc")


def test_invalid_request_is_rejected_before_storage_or_db(tmp_path: Path) -> None:
    called: list[str] = []

    class PathFactory:
        def __call__(self, **_kwargs):
            called.append("path")
            raise AssertionError("path must not be created for invalid flags")

    app = CollectionApplication(
        config_loader=lambda _path: _config(tmp_path),
        path_factory=PathFactory(),
        lock_factory=lambda: nullcontext(),
    )
    result = app.run(
        CollectionRequest(
            config_path=tmp_path / "config.yaml",
            refresh_active=False,
            refresh_active_only=True,
        )
    )

    assert result.exit_code == 2
    assert result.status == "INVALID"
    assert called == []


def test_month_and_date_conflict_is_rejected_before_config_or_lock(tmp_path: Path) -> None:
    called: list[str] = []

    app = CollectionApplication(
        config_loader=lambda _path: called.append("config"),
        lock_factory=lambda: (_ for _ in ()).throw(
            AssertionError("lock must not be created for invalid request")
        ),
    )

    result = app.run(
        CollectionRequest(
            config_path=tmp_path / "config.yaml",
            target_month="2026-08",
            start_date="2026-08-01",
            end_date="2026-08-31",
        )
    )

    assert result.exit_code == 2
    assert result.status == "INVALID"
    assert called == []


def test_missing_request_and_config_period_is_rejected_before_lock_or_storage(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    config.target_month = None
    called: list[str] = []

    app = CollectionApplication(
        config_loader=lambda _path: config,
        path_factory=lambda **_kwargs: called.append("path"),
        lock_factory=lambda: (_ for _ in ()).throw(
            AssertionError("lock must not be created without a collection period")
        ),
    )

    result = app.run(CollectionRequest(config_path=tmp_path / "config.yaml"))

    assert result.exit_code == 2
    assert result.status == "INVALID"
    assert "수집 기간" in (result.error or "")
    assert called == []


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("max_products", 0),
        ("max_products", -1),
        ("max_products", 1.5),
        ("max_versions", 0),
        ("max_versions", -1),
        ("max_versions", True),
    ],
)
def test_nonpositive_collection_limits_are_rejected_before_storage(
    tmp_path: Path, option: str, value: object
) -> None:
    app = CollectionApplication(
        config_loader=lambda _path: _config(tmp_path),
        path_factory=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("path must not be created for invalid limits")
        ),
        lock_factory=lambda: nullcontext(),
    )

    result = app.run(
        CollectionRequest(config_path=tmp_path / "config.yaml", **{option: value})
    )

    assert result.exit_code == 2
    assert result.status == "INVALID"


def test_global_lock_contention_is_exit_four_for_manual_application(tmp_path: Path) -> None:
    class Lock:
        def __enter__(self):
            raise AdvisoryLockUnavailable("busy")

        def __exit__(self, *_args):
            return False

    app = CollectionApplication(
        config_loader=lambda _path: _config(tmp_path),
        lock_factory=lambda: Lock(),
    )
    result = app.run(CollectionRequest(config_path=tmp_path / "config.yaml"))

    assert result == CollectionResult(4, "LOCKED", error="collection advisory lock unavailable")


def test_download_plan_is_not_repaired_before_global_lock(tmp_path: Path) -> None:
    plan_path = tmp_path / "download_plan.v3.jsonl"
    item = PlanItem(
        company_code="DB",
        company_name="DB손해보험",
        storage_name="DB손해보험",
        product_name_raw="테스트 상품",
        target_date="2026-08-01",
        document_type="POLICY",
        document_url="https://example.test/policy.pdf",
    )
    # PlanService는 정상 JSON이어도 마지막 newline이 없으면 파일을 복구한다.
    # 전역 lock 경합 중에는 그 쓰기조차 발생하지 않아야 한다.
    original = json.dumps(item.to_row(), ensure_ascii=False).encode("utf-8")
    plan_path.write_bytes(original)

    class BusyLock:
        def __enter__(self):
            raise AdvisoryLockUnavailable("busy")

        def __exit__(self, *_args):
            return False

    app = CollectionApplication(
        config_loader=lambda _path: _config(tmp_path),
        lock_factory=lambda: BusyLock(),
    )

    result = app.run(
        CollectionRequest(config_path=tmp_path / "config.yaml", download_plan=plan_path)
    )

    assert result.exit_code == 4
    assert plan_path.read_bytes() == original


class _Readiness:
    def __init__(self, ready: bool = True):
        self.ready = ready
        self.released = False

    def ensure(self, *, hold_migration_lock: bool):
        from crawler.db_readiness import DBReadinessResult

        if not self.ready:
            from crawler.db_readiness import DBReadinessError, DBReadinessResult

            raise DBReadinessError(DBReadinessResult(False, {"schema_columns": False}, ["bad schema"]))
        return DBReadinessResult(True, {"schema_columns": True}, [])

    def release_migration_lock(self):
        self.released = True


class _Manager:
    def __init__(self, summary_path: Path):
        self.summary_path = summary_path
        self.plan_paths = {}
        self.db_readiness = None

    def run(self):
        return {
            "run_id": "20260826_030000_abcdef",
            "computer_name": "TEST-PC",
            "process_id": 123,
            "started_at": "2026-08-26T03:00:00",
            "git_commit": "abc",
            "target_month": "2026-08",
            "scope_key": "2026-08",
            "period": {"start": "2026-08-01", "end": "2026-08-31"},
            "date_selection_mode": "new_or_revised",
            "elapsed_seconds": 0.1,
            "layout_version": 3,
            "artifact_paths": {"run": "99_운영/runs/2026/08/26/20260826_030000_abcdef"},
            "companies": {},
            "status_counts": {},
        }


@pytest.mark.parametrize(
    ("summary_update", "exit_code", "status"),
    [
        ({}, 0, "SUCCESS"),
        ({"status_counts": {"DOWNLOAD_FAILED": 1}}, 1, "FAILED"),
        ({"locked_companies": ["DB"]}, 4, "LOCKED"),
    ],
)
def test_application_maps_completed_summary_to_exit_codes(
    tmp_path: Path, summary_update, exit_code: int, status: str, monkeypatch
) -> None:
    class Repository:
        closed = False

        def close(self):
            self.closed = True

    repository = Repository()
    readiness = _Readiness()
    manager_holder: list[_Manager] = []
    pushed: list[str] = []
    reset: list[object] = []
    trace_token = object()
    monkeypatch.setattr(
        "app.application.collection.push_trace_id",
        lambda value: pushed.append(value) or trace_token,
    )
    monkeypatch.setattr(
        "app.application.collection.reset_trace_id",
        lambda value: reset.append(value),
    )

    def manager_factory(_config, _options, **kwargs):
        manager = _Manager(tmp_path / "summary.json")
        original = manager.run

        def run():
            summary = original()
            summary.update(summary_update)
            return summary

        manager.run = run
        manager_holder.append(manager)
        assert kwargs["paths"] is not None
        return manager

    app = CollectionApplication(
        config_loader=lambda _path: _config(tmp_path),
        context_factory=_context,
        manager_factory=manager_factory,
        repository_factory=lambda: repository,
        readiness_factory=lambda *_args, **_kwargs: readiness,
        lock_factory=lambda: nullcontext(),
    )
    result = app.run(CollectionRequest(config_path=tmp_path / "config.yaml"))

    assert result.exit_code == exit_code
    assert result.status == status
    assert readiness.released is True
    assert repository.closed is True
    assert manager_holder
    assert pushed == ["20260826_030000_run1"]
    assert reset == [trace_token]


def test_startup_validation_reuses_storage_and_db_contract(tmp_path: Path) -> None:
    class Repository:
        closed = False

        def close(self):
            self.closed = True

    repository = Repository()
    readiness = _Readiness()
    app = CollectionApplication(
        config_loader=lambda _path: _config(tmp_path),
        repository_factory=lambda: repository,
        readiness_factory=lambda *_args, **_kwargs: readiness,
    )

    result = app.validate_startup_environment(tmp_path / "config.yaml")

    assert result.exit_code == 0
    assert result.checks == {"storage": True, "database": True}
    assert repository.closed is True
