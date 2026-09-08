"""서버 측 APScheduler 설정 조회 API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.scheduling.scheduler import SchedulerSettings


router = APIRouter(prefix="/api/v1/schedule", tags=["schedule"])


@router.get("")
def get_schedule(request: Request) -> dict[str, Any]:
    """FastAPI lifespan scheduler의 현재 설정과 실행 상태를 반환한다.

    이 API로 scheduler를 변경하지는 않는다. 비밀번호/DB 접속정보도 포함하지
    않는다.
    """

    try:
        settings = SchedulerSettings.from_env()
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"scheduler configuration is unavailable: {exc}") from exc
    scheduler = getattr(request.app.state, "scheduler", None)
    return {
        "running": bool(scheduler is not None and scheduler.running),
        "execution_mode": "fastapi_lifespan",
        "cron": settings.cron,
        "timezone": settings.timezone,
        "config_path": settings.config_path,
        "period_mode": settings.period_mode,
        "target_month": settings.target_month,
        "start_date": settings.start_date,
        "end_date": settings.end_date,
        "companies": list(settings.companies),
        "misfire_grace_time": settings.misfire_grace_time,
        "max_instances": 1,
        "coalesce": True,
        "job_id": "scheduled-collection",
        "storage": "memory",
    }
