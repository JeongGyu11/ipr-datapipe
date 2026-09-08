"""Command-line adapter for the collection application."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.application.collection import CollectionApplication, CollectionRequest, CollectionResult
from app.config_paths import DEFAULT_CONFIG_PATH, resolve_config_path
from app.core.ipr_logger import configure_logging, get_logger
from app.core.settings import SettingsError, get_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="생명·손해보험사 상품공시실 약관/상품요약서/사업방법서 자동 수집기",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="설정 파일 경로 (기본: 프로젝트 루트의 config.yaml)")
    range_group = parser.add_mutually_exclusive_group()
    range_group.add_argument("--target-month", help="수집 대상 월 (YYYY-MM). 미지정 시 config.yaml 값 사용")
    range_group.add_argument("--start-date", help="수집 시작일 (YYYY-MM-DD). --end-date와 함께 사용")
    parser.add_argument("--end-date", help="수집 종료일 (YYYY-MM-DD). --start-date와 함께 사용")
    parser.add_argument("--company", action="append", default=[], help="특정 보험사만 실행 (여러 번 지정 가능). 예: --company DB")
    parser.add_argument("--dry-run", action="store_true", help="파일을 받지 않고 대상 상품/문서 링크/예상 경로만 수집")
    parser.add_argument("--write-plan", action="store_true", help="수집한 문서를 재수집 없는 다운로드 plan(JSONL)으로 저장")
    parser.add_argument("--download-plan", metavar="PATH", help="저장된 plan을 사용해 목록/상세 재수집 없이 다운로드")
    parser.add_argument("--retry-failed", action="store_true", help="이전 실행에서 실패한 항목만 다시 시도")
    parser.add_argument("--no-refresh-active", dest="refresh_active", action="store_false", default=True, help="DB에 저장된 판매중 상품 상태 재확인을 생략")
    parser.add_argument("--refresh-active-only", action="store_true", help="기존 판매중 상품 상태와 폴더만 갱신")
    parser.add_argument("--rename-dry-run", action="store_true", help="판매상태 폴더 이동을 미리보기만 수행")
    parser.add_argument("--max-products", type=int, default=None, help="보험사별 조회 상품 수 상한(테스트용)")
    parser.add_argument("--max-versions", type=int, default=None, help="보험사별 처리 상품 버전 수 상한(테스트용)")
    parser.add_argument("--verbose", action="store_true", help="상세 로그 출력")
    parser.add_argument("--lock-status", action="store_true", help="현재 보험사별 실행 잠금 상태를 출력하고 종료")
    parser.add_argument("--force-unlock", metavar="CODE", help="비정상 종료 후 남은 보험사 잠금을 명시적으로 해제하고 종료")
    return parser


def request_from_args(args: argparse.Namespace) -> CollectionRequest:
    return CollectionRequest(
        config_path=resolve_config_path(args.config),
        target_month=args.target_month,
        start_date=args.start_date,
        end_date=args.end_date,
        companies=tuple(args.company or ()),
        dry_run=args.dry_run,
        write_plan=args.write_plan,
        download_plan=Path(args.download_plan) if args.download_plan else None,
        retry_failed=args.retry_failed,
        refresh_active=args.refresh_active,
        refresh_active_only=args.refresh_active_only,
        rename_dry_run=args.rename_dry_run,
        max_products=args.max_products,
        max_versions=args.max_versions,
        verbose=args.verbose,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        configure_logging(get_settings().logging, verbose=args.verbose)
    except SettingsError as exc:
        print(f"애플리케이션 설정 오류: {exc}", file=sys.stderr)
        return 2
    application = CollectionApplication()
    if args.lock_status and args.force_unlock:
        logger = get_logger(__name__)
        logger.error("--lock-status 와 --force-unlock 은 함께 사용할 수 없습니다.")
        return 2
    if args.lock_status:
        return application.lock_status(resolve_config_path(args.config), verbose=args.verbose).exit_code
    if args.force_unlock:
        return application.force_unlock(resolve_config_path(args.config), args.force_unlock, verbose=args.verbose).exit_code
    result: CollectionResult = application.run(request_from_args(args))
    return result.exit_code


__all__ = ["build_parser", "main", "request_from_args"]
