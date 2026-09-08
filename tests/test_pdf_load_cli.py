"""PDF Load CLI 계약과 기존 수집 명령 분기 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

import main as root_main
from app.load_cli import build_parser, main, request_from_args
from app.load_settings import PdfLoadSettingsError


def test_load_cli_requires_pdf() -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args([])
    assert exc_info.value.code == 2


def test_load_cli_accepts_repeated_pdf_only() -> None:
    args = build_parser().parse_args(["--pdf", "가.pdf", "--pdf", "나.pdf"])
    request = request_from_args(args)
    assert request.pdf_paths == (Path("가.pdf"), Path("나.pdf"))


@pytest.mark.parametrize("option", ["--output", "--force", "--dry-run", "--verbose"])
def test_removed_load_options_are_rejected(option: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["--pdf", "가.pdf", option])
    assert exc_info.value.code == 2


def test_root_main_routes_load_without_changing_collection(monkeypatch) -> None:
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr("app.load_cli.main", lambda args: calls.append(("load", args)) or 7)
    monkeypatch.setattr(root_main, "collection_main", lambda args: calls.append(("collect", args)) or 8)

    assert root_main.main(["load", "--pdf", "sample.pdf"]) == 7
    assert root_main.main(["--target-month", "2026-08"]) == 8
    assert calls == [
        ("load", ["--pdf", "sample.pdf"]),
        ("collect", ["--target-month", "2026-08"]),
    ]


def test_load_cli_reports_invalid_settings_without_traceback(monkeypatch, capsys) -> None:
    class InvalidSettingsApplication:
        def __init__(self, **_kwargs):
            raise PdfLoadSettingsError("잘못된 설정")

    monkeypatch.setattr("app.load_cli.PdfLoadApplication", InvalidSettingsApplication)

    assert main(["--pdf", "sample.pdf"]) == 2
    assert "PDF Load 설정 오류" in capsys.readouterr().err
