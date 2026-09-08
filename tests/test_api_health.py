from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.application.collection import CollectionResult


def successful_startup(_config_path) -> CollectionResult:
    return CollectionResult(0, "SUCCESS", checks={"database": True, "storage": True})


class FakeScheduler:
    running = False

    def start(self) -> None:
        self.running = True

    def shutdown(self, *, wait: bool) -> None:
        self.running = False


def test_live_endpoint_does_not_require_startup() -> None:
    response = TestClient(create_app()).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_requires_completed_startup() -> None:
    response = TestClient(create_app()).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == "startup validation is not complete"


def test_ready_uses_startup_snapshot_and_scheduler_state_only() -> None:
    scheduler = FakeScheduler()
    application = create_app(
        scheduler_factory=lambda: scheduler,
        startup_validator=successful_startup,
    )

    with TestClient(application) as client:
        assert client.get("/health/ready").json() == {"status": "ready"}
        scheduler.running = False
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["detail"] == "scheduler is not running"


def test_startup_validation_runs_once_and_failure_prevents_scheduler_start() -> None:
    calls: list[object] = []
    scheduler = FakeScheduler()

    def validator(path):
        calls.append(path)
        return successful_startup(path)

    application = create_app(
        scheduler_factory=lambda: scheduler,
        startup_validator=validator,
    )
    with TestClient(application) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.get("/health/ready").status_code == 200
    assert len(calls) == 1

    started: list[bool] = []

    class TrackingScheduler(FakeScheduler):
        def start(self) -> None:
            started.append(True)
            super().start()

    def failed_validator(_path):
        return CollectionResult(3, "INFRA_ERROR", error="DB unavailable", checks={"database": False, "storage": True})

    with pytest.raises(RuntimeError, match="startup environment validation failed"):
        with TestClient(
            create_app(
                scheduler_factory=TrackingScheduler,
                startup_validator=failed_validator,
            )
        ):
            pass
    assert started == []


def test_fastapi_lifespan_starts_and_stops_embedded_scheduler() -> None:
    events: list[str] = []

    class RecordingScheduler(FakeScheduler):
        def start(self) -> None:
            events.append("start")
            super().start()

        def shutdown(self, *, wait: bool) -> None:
            events.append(f"shutdown:{wait}")
            super().shutdown(wait=wait)

    scheduler = RecordingScheduler()
    application = create_app(
        scheduler_factory=lambda: scheduler,
        startup_validator=successful_startup,
    )

    with TestClient(application) as client:
        response = client.get("/api/v1/schedule")
        assert events == ["start"]
        assert response.status_code == 200
        assert response.json()["running"] is True

    assert events == ["start", "shutdown:True"]


def test_fastapi_lifespan_cleans_up_partially_started_scheduler() -> None:
    events: list[str] = []

    class FailingScheduler(FakeScheduler):
        def start(self) -> None:
            events.append("start")
            self.running = True
            raise RuntimeError("scheduler startup failed")

        def shutdown(self, *, wait: bool) -> None:
            events.append(f"shutdown:{wait}")
            self.running = False

    application = create_app(
        scheduler_factory=FailingScheduler,
        startup_validator=successful_startup,
    )

    with pytest.raises(RuntimeError, match="scheduler startup failed"):
        with TestClient(application):
            pass

    assert events == ["start", "shutdown:False"]
    assert application.state.scheduler is None


def test_fastapi_lifespan_clears_state_when_shutdown_fails() -> None:
    class FailingShutdownScheduler(FakeScheduler):
        def shutdown(self, *, wait: bool) -> None:
            raise RuntimeError(f"shutdown failed: wait={wait}")

    application = create_app(
        scheduler_factory=FailingShutdownScheduler,
        startup_validator=successful_startup,
    )

    with pytest.raises(RuntimeError, match="shutdown failed: wait=True"):
        with TestClient(application):
            pass

    assert application.state.scheduler is None
    assert application.state.startup_complete is False
