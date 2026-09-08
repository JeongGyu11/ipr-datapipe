from __future__ import annotations

from fastapi.testclient import TestClient

import app.api.main as api_main
from app.api.main import create_app


def test_request_id_is_sanitized_bounded_and_echoed() -> None:
    application = create_app()
    supplied = "  client-123/ " + ("x" * 200)

    response = TestClient(application).get("/health/live", headers={"X-Request-ID": supplied})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "client-123" + ("x" * 118)


def test_blank_request_id_is_replaced_with_uuid(monkeypatch) -> None:
    monkeypatch.setattr(api_main, "uuid4", lambda: type("UUID", (), {"hex": "generated-id"})())

    response = TestClient(create_app()).get("/health/live", headers={"X-Request-ID": " \t"})

    assert response.headers["X-Request-ID"] == "generated-id"


def test_request_trace_context_is_reset_when_handler_raises(monkeypatch) -> None:
    pushed: list[str] = []
    reset: list[object] = []

    def push(value: str):
        pushed.append(value)
        return object()

    def reset_trace(token: object) -> None:
        reset.append(token)

    monkeypatch.setattr(api_main, "push_trace_id", push)
    monkeypatch.setattr(api_main, "reset_trace_id", reset_trace)

    application = create_app()

    @application.get("/test-error")
    def test_error() -> None:
        raise RuntimeError("boom")

    client = TestClient(application, raise_server_exceptions=False)
    response = client.get("/test-error", headers={"X-Request-ID": "trace-1"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "trace-1"
    assert pushed == ["trace-1"]
    assert len(reset) == 1
