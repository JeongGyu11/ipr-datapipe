"""프로세스 실행 정보 로딩 테스트."""

from pathlib import Path

import pytest

from app.application.reporting import log_summary
from app.cli import build_parser, main as run_main
from crawler.run_context import RunContext
from utils.crawler_logger import setup_logging


def test_context_does_not_read_or_record_operator(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("CRAWLER_OPERATOR=택신\n", encoding="utf-8")
    monkeypatch.setenv("CRAWLER_OPERATOR", "환경변수사용자")
    context = RunContext.create(tmp_path)
    assert not hasattr(context, "operator")
    assert "operator" not in context.to_dict()


def test_summary_is_emitted_as_one_multiline_log_record(capsys) -> None:
    setup_logging(None)
    log_summary(
        {
            "run_id": "RUN-1",
            "scope_key": "20240101_20260820",
            "period": {"start": "2024-01-01", "end": "2026-08-20"},
            "date_selection_mode": "new_or_revised",
            "elapsed_seconds": 1.2,
            "artifact_paths": {"documents": "01_문서"},
            "companies": {},
            "status_counts": {"DOWNLOADED": 1},
        }
    )

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "실행 ID       : RUN-1" in output
    assert "전체 상태     : {\"DOWNLOADED\": 1}" in output


def test_operator_cli_option_is_not_supported() -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["--operator", "택신"])

    assert exc_info.value.code == 2


def test_target_month_and_start_date_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args([
            "--target-month", "2026-07",
            "--start-date", "2024-01-01",
            "--end-date", "2026-08-20",
        ])

    assert exc_info.value.code == 2


def test_active_refresh_flags_parse_with_expected_defaults() -> None:
    args = build_parser().parse_args(["--refresh-active-only", "--rename-dry-run"])

    assert args.refresh_active is True
    assert args.refresh_active_only is True
    assert args.rename_dry_run is True


@pytest.mark.parametrize("flag", ["--refresh-active-only", "--rename-dry-run"])
def test_status_refresh_flags_cannot_be_combined_with_no_refresh(flag) -> None:
    # Flag validation runs before output path verification/network access.
    assert run_main([flag, "--no-refresh-active"]) == 2


@pytest.mark.parametrize(
    "args",
    [
        ["--start-date", "2024-01-01"],
        ["--end-date", "2026-08-20"],
    ],
)
def test_start_and_end_date_must_be_provided_together(args) -> None:
    # 범위 검증은 파일서버 접근 전에 끝나므로 외부 상태를 사용하지 않는다.
    assert run_main(args) == 2
