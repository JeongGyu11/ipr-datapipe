"""PDF Load 전용 CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.application.pdf_load import PdfLoadApplication
from app.core.ipr_logger import configure_logging
from app.core.settings import SettingsError, get_settings
from app.domain.pdf_load import PdfLoadRequest
from app.infrastructure.llm import TableReconstructionService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py load",
        description="명시한 PDF를 복사하고 페이지·표·이미지 산출물로 Load합니다.",
    )
    parser.add_argument(
        "--pdf",
        action="append",
        required=True,
        metavar="PATH",
        help="처리할 PDF 경로. 여러 파일은 --pdf를 반복해서 지정",
    )
    return parser


def request_from_args(args: argparse.Namespace) -> PdfLoadRequest:
    return PdfLoadRequest(pdf_paths=tuple(Path(value) for value in args.pdf))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = get_settings()
        configure_logging(settings.logging)
        table_reconstructor = None
        if settings.pdf_load.table_reconstruction_enabled:
            llm = settings.llm.validate_for_table_reconstruction()
            table_reconstructor = TableReconstructionService(
                base_url=str(llm.base_url),
                model=str(llm.model),
                api_key=llm.api_key,
                timeout=llm.request_timeout_seconds,
                max_output_tokens=llm.max_output_tokens,
            )
        result = PdfLoadApplication(
            header_footer_enabled=settings.pdf_load.header_footer_enabled,
            table_reconstructor=table_reconstructor,
        ).run(request_from_args(args))
    except SettingsError as exc:
        print(f"PDF Load 설정 오류: {exc}", file=sys.stderr)
        return 2
    return result.exit_code


__all__ = ["build_parser", "main", "request_from_args"]
