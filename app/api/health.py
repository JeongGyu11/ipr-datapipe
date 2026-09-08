"""프로세스 생존 및 startup snapshot readiness 엔드포인트."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/health", tags=["health"])


@dataclass(frozen=True)
class ReadinessSnapshot:
    """One successful startup probe result reused by readiness requests."""

    database: bool
    storage: bool
    checked_at: str

    @property
    def ready(self) -> bool:
        return self.database and self.storage


@router.get("/live")
def live() -> dict[str, str]:
    """프로세스가 요청을 처리할 수 있는지 확인한다."""

    return {"status": "ok"}


@router.get("/ready")
def ready(request: Request) -> dict[str, str]:
    """Return only the successful startup validation state.

    Readiness never probes PostgreSQL or SMB itself; doing so on every health
    poll would create unnecessary writes and can mask a failed startup.
    """

    snapshot = getattr(request.app.state, "readiness", None)
    if not bool(getattr(request.app.state, "startup_complete", False)):
        raise HTTPException(status_code=503, detail="startup validation is not complete")
    if snapshot is None or not snapshot.ready:
        raise HTTPException(status_code=503, detail="startup dependencies are not ready")
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None or not bool(getattr(scheduler, "running", False)):
        raise HTTPException(status_code=503, detail="scheduler is not running")
    return {"status": "ready"}
