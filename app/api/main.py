"""FastAPI 애플리케이션 진입점.

APScheduler는 별도 서비스가 아니라 애플리케이션 lifespan에서 시작·종료한다.
실제 수집은 scheduler 작업 스레드에서 실행하며, API 요청 처리는 조회 전용이다.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response

from app.api.dependencies import config_file_path
from app.api.health import ReadinessSnapshot, router as health_router
from app.api.routers.collectors import router as collectors_router
from app.api.routers.runs import router as runs_router
from app.api.routers.schedule import router as schedule_router
from app.application.collection import CollectionApplication, CollectionResult
from app.core.ipr_logger import configure_logging, get_logger, push_trace_id, reset_trace_id
from app.core.settings import get_settings
from app.scheduling.scheduler import create_scheduler


# Configure the common logger at import time so ``uvicorn app.api.main:app``
# receives the same handlers and format as every other application entrypoint.
# Calling this once here also avoids uvicorn's default handlers being added again
# when the module is imported directly by the worker process.
configure_logging(get_settings().logging)
LOGGER = get_logger(__name__)

_REQUEST_ID_ALLOWED = re.compile(r"[^A-Za-z0-9._:-]")
_REQUEST_ID_MAX_LENGTH = 128


def _sanitize_request_id(value: str | None) -> str | None:
    """Return a bounded, log-safe request ID supplied by a caller.

    Request IDs are copied into response headers and structured log context, so
    control characters and punctuation that can alter log/header syntax are
    removed.  Empty values are treated as absent by the middleware.
    """

    if value is None:
        return None
    sanitized = _REQUEST_ID_ALLOWED.sub("", value.strip())[:_REQUEST_ID_MAX_LENGTH]
    return sanitized or None


def _request_id(request: Request) -> str:
    supplied = _sanitize_request_id(request.headers.get("X-Request-ID"))
    return supplied or uuid4().hex


def create_app(
    *,
    scheduler_factory: Callable[[], Any] | None = None,
    startup_validator: Callable[[Path], CollectionResult] | None = None,
) -> FastAPI:
    factory = scheduler_factory or create_scheduler
    validator = startup_validator or CollectionApplication().validate_startup_environment

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        validation = validator(config_file_path())
        if validation.exit_code != 0:
            raise RuntimeError(
                "FastAPI startup environment validation failed: "
                f"{validation.error or validation.status}"
            )
        checks = validation.checks or {}
        if not checks.get("database", False) or not checks.get("storage", False):
            raise RuntimeError("FastAPI startup environment checks are incomplete")
        application.state.startup_validation = validation
        application.state.readiness = ReadinessSnapshot(
            database=True,
            storage=True,
            checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        scheduler = factory()
        application.state.scheduler = scheduler
        try:
            scheduler.start()
        except BaseException:
            # start가 executor/thread 일부를 만든 뒤 실패한 경우도 정리한다.
            # shutdown 자체 오류가 원래 startup 오류를 가리지는 않게 한다.
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                LOGGER.exception("failed to clean up scheduler after startup error")
            application.state.scheduler = None
            raise
        LOGGER.info("FastAPI lifespan collection scheduler started")
        application.state.startup_complete = True
        try:
            yield
        finally:
            # 실행 중 수집의 CompanyLock/체크포인트 정리가 끝날 때까지 기다린다.
            # Docker stop_grace_period가 운영상 최대 대기 시간을 제한한다.
            try:
                scheduler.shutdown(wait=True)
            finally:
                application.state.startup_complete = False
                application.state.scheduler = None
                LOGGER.info("FastAPI lifespan collection scheduler stopped")

    app = FastAPI(
        title="Insurance Document Crawler",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context_middleware(
        request: Request,
        call_next: Callable[..., Any],
    ) -> Response:
        """Attach one bounded request ID to logs and the HTTP response."""

        request_id = _request_id(request)
        request.state.request_id = request_id
        token = push_trace_id(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            reset_trace_id(token)

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        """Return a traceable 500 response without exposing exception details."""

        request_id = str(getattr(request.state, "request_id", "") or uuid4().hex)
        LOGGER.error(
            "Unhandled API request error",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
            headers={"X-Request-ID": request_id},
        )

    app.state.scheduler = None
    app.state.startup_validation = None
    app.state.readiness = None
    app.state.startup_complete = False
    app.include_router(health_router)
    app.include_router(collectors_router)
    app.include_router(runs_router)
    app.include_router(schedule_router)
    return app


app = create_app()
