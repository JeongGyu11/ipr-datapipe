from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies import get_app_config, get_path_service
from app.api.main import create_app
from app.api.routers.runs import get_run
from app.core.settings import get_settings
from crawler.config import AppConfig
from crawler.path_service import PathService


def _config() -> AppConfig:
    return AppConfig(
        target_month="2026-08",
        base_path="",
        root_folder="상품공시실문서",
        crawler={},
        download={},
        document_types={},
        document_exclude_keywords=[],
        date_selection_mode="new_or_revised",
    )


def _write_summary(paths: PathService, run_id: str, *, finished_at: str) -> None:
    path = paths.run_dir(run_id) / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"layout_version": 3, "run_id": run_id, "run_status": "SUCCESS", "finished_at": finished_at}),
        encoding="utf-8",
    )


def test_api_path_service_uses_non_period_scope_when_target_month_is_null() -> None:
    config = _config()
    config.target_month = None

    paths = get_path_service(config)

    assert paths.target_month == "config"
    assert paths.scope_component == "config"


def test_collectors_is_read_only_config_projection() -> None:
    application = create_app()
    application.dependency_overrides[get_app_config] = _config
    try:
        response = TestClient(application).get("/api/v1/collectors")
    finally:
        application.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["collectors"][0]["code"] == "DB"
    assert response.json()["collectors"][0]["enabled"] is True
    assert response.json()["collectors"][0]["collection_status"] == "ACTIVE"
    assert response.json()["collectors"][0]["storage_name"] == "DB손해보험"


def test_collectors_exposes_catalog_status_and_adapter_availability() -> None:
    application = create_app()
    application.dependency_overrides[get_app_config] = _config
    try:
        response = TestClient(application).get("/api/v1/collectors")
    finally:
        application.dependency_overrides.clear()

    assert response.status_code == 200
    collectors = {item["code"]: item for item in response.json()["collectors"]}
    assert collectors["DB"]["adapter_available"] is True
    assert collectors["FUBON_HYUNDAI_LIFE"]["collection_status"] == "ACCESS_RESTRICTED"
    assert collectors["FUBON_HYUNDAI_LIFE"]["enabled"] is False


def test_latest_and_explicit_run_use_existing_summary_files(tmp_path: Path) -> None:
    paths = PathService(
        base_path=str(tmp_path),
        root_folder="output",
        target_month="2026-08",
        storage_kind="local",
    )
    _write_summary(paths, "20260825_030000_aaaaaa", finished_at="2026-08-25T03:00:00")
    _write_summary(paths, "20260826_030000_bbbbbb", finished_at="2026-08-26T03:00:00")

    application = create_app()
    application.dependency_overrides[get_path_service] = lambda: paths
    try:
        client = TestClient(application)
        latest = client.get("/api/v1/runs/latest")
        explicit = client.get("/api/v1/runs/20260825_030000_aaaaaa")
    finally:
        application.dependency_overrides.clear()

    assert latest.status_code == 200
    assert latest.json()["run_id"] == "20260826_030000_bbbbbb"
    assert explicit.status_code == 200
    assert explicit.json()["run_id"] == "20260825_030000_aaaaaa"


def test_latest_run_does_not_recursively_scan_the_entire_storage(
    tmp_path: Path, monkeypatch
) -> None:
    paths = PathService(
        base_path=str(tmp_path), root_folder="output", target_month="2026-08", storage_kind="local"
    )
    _write_summary(paths, "20260826_030000_bbbbbb", finished_at="2026-08-26T03:00:00")
    monkeypatch.setattr(
        Path,
        "rglob",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("rglob must not run")),
    )

    application = create_app()
    application.dependency_overrides[get_path_service] = lambda: paths
    try:
        response = TestClient(application).get("/api/v1/runs/latest")
    finally:
        application.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["run_id"] == "20260826_030000_bbbbbb"


def test_latest_run_skips_corrupt_and_incomplete_newer_summaries(tmp_path: Path) -> None:
    paths = PathService(
        base_path=str(tmp_path), root_folder="output", target_month="2026-08", storage_kind="local"
    )
    valid_run_id = "20260826_010000_aaaaaa"
    _write_summary(paths, valid_run_id, finished_at="2026-08-26T01:00:00")

    incomplete_run_id = "20260826_020000_bbbbbb"
    incomplete_path = paths.run_dir(incomplete_run_id) / "summary.json"
    incomplete_path.parent.mkdir(parents=True, exist_ok=True)
    incomplete_path.write_text(
        json.dumps({"run_id": incomplete_run_id, "run_status": "RUNNING"}),
        encoding="utf-8",
    )

    corrupt_run_id = "20260826_030000_cccccc"
    corrupt_path = paths.run_dir(corrupt_run_id) / "summary.json"
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_path.write_text("{not-json", encoding="utf-8")

    application = create_app()
    application.dependency_overrides[get_path_service] = lambda: paths
    try:
        response = TestClient(application).get("/api/v1/runs/latest")
    finally:
        application.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["run_id"] == valid_run_id


def test_latest_run_reports_storage_failure_as_service_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    paths = PathService(base_path=str(tmp_path), root_folder="output", storage_kind="local")
    original_scandir = os.scandir

    def failing_scandir(path):
        if Path(path) == paths.runs_root:
            raise PermissionError("storage denied")
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", failing_scandir)
    application = create_app()
    application.dependency_overrides[get_path_service] = lambda: paths
    try:
        response = TestClient(application).get("/api/v1/runs/latest")
    finally:
        application.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "run storage unavailable"}


def test_latest_run_reports_summary_read_failure_as_service_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    paths = PathService(
        base_path=str(tmp_path), root_folder="output", target_month="2026-08", storage_kind="local"
    )
    _write_summary(paths, "20260826_030000_bbbbbb", finished_at="2026-08-26T03:00:00")
    original_open = Path.open

    def failing_summary_open(path: Path, *args, **kwargs):
        if path.name == "summary.json":
            raise PermissionError("summary denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_summary_open)
    application = create_app()
    application.dependency_overrides[get_path_service] = lambda: paths
    try:
        response = TestClient(application).get("/api/v1/runs/latest")
    finally:
        application.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "run storage unavailable"}


def test_runs_reject_path_traversal_and_missing_runs(tmp_path: Path) -> None:
    paths = PathService(base_path=str(tmp_path), root_folder="output", storage_kind="local")
    application = create_app()
    application.dependency_overrides[get_path_service] = lambda: paths
    try:
        client = TestClient(application)
        traversal = client.get("/api/v1/runs/%2E%2E")
        invalid_date = client.get("/api/v1/runs/20260230_invalid")
        missing_date = client.get("/api/v1/runs/not-a-run")
        missing = client.get("/api/v1/runs/20260826_030000_missing")
    finally:
        application.dependency_overrides.clear()

    assert traversal.status_code == 400
    assert invalid_date.status_code == 400
    assert missing_date.status_code == 400
    assert missing.status_code == 404

    with pytest.raises(HTTPException) as error:
        get_run("../secret", paths)
    assert error.value.status_code == 400


def test_schedule_is_read_only_and_does_not_expose_database(monkeypatch) -> None:
    monkeypatch.setenv("IPR_SCHEDULE_CRON", "15 2 * * *")
    monkeypatch.setenv("IPR_SCHEDULE_COMPANIES", "DB,KB")
    monkeypatch.setenv("IPR_SCHEDULE_PERIOD_MODE", "previous_day")
    monkeypatch.setenv("CRAWLER_CONFIG_PATH", "./configs/custom.yaml")
    monkeypatch.setenv("RS_DB_PASSWORD", "must-not-appear")
    get_settings(reload=True)

    response = TestClient(create_app()).get("/api/v1/schedule")

    assert response.status_code == 200
    body = response.json()
    assert body["cron"] == "15 2 * * *"
    assert body["companies"] == ["DB", "KB"]
    assert body["config_path"] == "./configs/custom.yaml"
    assert body["max_instances"] == 1
    assert "must-not-appear" not in response.text
