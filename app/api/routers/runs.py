"""기존 ``99_운영/runs`` 실행 summary 조회 API.

이 라우터는 파일 서버에 저장된 summary JSON만 읽는다. DB에 실행 이력
테이블을 만들거나 수집 상태를 변경하지 않는다.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.dependencies import PathServiceDependency
from utils.network_io import retry_file_operation, strict_is_file


router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

# RunContext가 생성하는 형식(YYYYMMDD_HHMMSS_xxxxxx)과 향후 호환 가능한
# 안전한 식별자만 허용한다. 경로 구분자/점 세그먼트는 모두 거부한다.
_SAFE_RUN_ID = re.compile(r"^\d{8}[A-Za-z0-9_.-]{0,120}$")
_YEAR = re.compile(r"^\d{4}$")
_MONTH_OR_DAY = re.compile(r"^\d{2}$")
_TERMINAL_RUN_STATUSES = {"SUCCESS", "FAILED", "PARTIAL_SUCCESS", "LOCKED"}


class _RunStorageUnavailable(RuntimeError):
    """실행 이력 저장소를 읽을 수 없는 상태."""


def _validate_run_id(run_id: str) -> str:
    if (
        not run_id
        or run_id in {".", ".."}
        or "/" in run_id
        or "\\" in run_id
        or "\x00" in run_id
        or not _SAFE_RUN_ID.fullmatch(run_id)
    ):
        raise HTTPException(status_code=400, detail="invalid run_id")
    try:
        datetime.strptime(run_id[:8], "%Y%m%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid run_id") from exc
    return run_id


def _inside(root: Path, candidate: Path) -> Path:
    """candidate가 root 아래에 있는지 확인해 symlink traversal도 막는다."""

    try:
        root_resolved = root.resolve(strict=False)
        candidate_resolved = candidate.resolve(strict=False)
        candidate_resolved.relative_to(root_resolved)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="run not found")
    return candidate_resolved


def _summary_from_path(path: Path) -> dict[str, Any] | None:
    try:
        def _read() -> dict[str, Any]:
            with path.open("r", encoding="utf-8") as fp:
                return json.load(fp)
        value = retry_file_operation(_read, path=path, operation_name="summary 읽기")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _RunStorageUnavailable from exc
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _is_completed_summary(summary: dict[str, Any] | None, run_id: str) -> bool:
    """최종 기록까지 완료된 현재 형식의 summary인지 확인한다."""

    if summary is None or summary.get("run_id") != run_id:
        return False
    if summary.get("layout_version") != 3:
        return False
    finished_at = summary.get("finished_at")
    return (
        isinstance(finished_at, str)
        and bool(finished_at.strip())
        and summary.get("run_status") in _TERMINAL_RUN_STATUSES
    )


def _safe_child_dirs(root: Path, pattern: re.Pattern[str] | None = None) -> list[Path]:
    """root 바로 아래의 안전한 디렉터리만 이름 역순으로 반환한다."""

    try:
        def _scan() -> list[Path]:
            found: list[Path] = []
            with os.scandir(root) as entries:
                for entry in entries:
                    if pattern is not None and not pattern.fullmatch(entry.name):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        found.append(Path(entry.path))
            return found
        children = retry_file_operation(_scan, path=root, operation_name="runs 디렉터리 열거")
        return sorted(children, key=lambda item: item.name, reverse=True)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise _RunStorageUnavailable from exc


def _latest_summary(runs_root: Path) -> dict[str, Any] | None:
    # runs/{YYYY}/{MM}/{DD}/{run_id} 규칙을 이용한다. SMB 전체를 rglob하면
    # 운영 이력이 많을 때 readiness/API가 수분간 멈출 수 있으므로 최신 날짜부터
    # 한 단계씩 내려가고, 유효한 summary가 있는 첫 날짜에서 탐색을 끝낸다.
    for year_dir in _safe_child_dirs(runs_root, _YEAR):
        for month_dir in _safe_child_dirs(year_dir, _MONTH_OR_DAY):
            for day_dir in _safe_child_dirs(month_dir, _MONTH_OR_DAY):
                for run_dir in _safe_child_dirs(day_dir, _SAFE_RUN_ID):
                    path = run_dir / "summary.json"
                    summary = _summary_from_path(path)
                    if _is_completed_summary(summary, run_dir.name):
                        return summary

    return None


@router.get("/latest")
def latest_run(paths: PathServiceDependency) -> dict[str, Any]:
    """가장 최근 완료된 실행 summary를 반환한다."""

    try:
        summary = _latest_summary(paths.runs_root)
    except _RunStorageUnavailable as exc:
        raise HTTPException(status_code=503, detail="run storage unavailable") from exc
    if summary is None:
        raise HTTPException(status_code=404, detail="no run summary found")
    return summary


@router.get("/{run_id}")
def get_run(run_id: str, paths: PathServiceDependency) -> dict[str, Any]:
    """지정한 run_id의 summary를 반환한다."""

    safe_run_id = _validate_run_id(run_id)
    runs_root = paths.runs_root
    summary_path = _inside(runs_root, paths.run_dir(safe_run_id) / "summary.json")
    try:
        is_file = retry_file_operation(
            lambda: strict_is_file(summary_path),
            path=summary_path,
            operation_name="summary 확인",
        )
    except OSError as exc:
        raise HTTPException(status_code=503, detail="run storage unavailable") from exc
    if not is_file:
        raise HTTPException(status_code=404, detail="run not found")
    summary = _summary_from_path(summary_path)
    if not _is_completed_summary(summary, safe_run_id):
        raise HTTPException(status_code=404, detail="run not found")
    return summary
