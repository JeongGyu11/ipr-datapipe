"""CLI에서 명시한 로컬 PDF 경로 선택과 사전 검증."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from app.domain.pdf_load import LoadTarget
from crawler.validators import has_valid_magic


class PdfInputError(ValueError):
    """Load 입력 PDF가 계약을 만족하지 않을 때 발생한다."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class LocalPdfSelector:
    def select(self, values: Sequence[str | Path]) -> list[LoadTarget]:
        if not values:
            raise PdfInputError("PDF_REQUIRED", "--pdf를 한 번 이상 지정해야 합니다.")
        return [
            LoadTarget(input_index=index, source_path=Path(value).expanduser().resolve())
            for index, value in enumerate(values, start=1)
        ]

    @staticmethod
    def validate(target: LoadTarget) -> LoadTarget:
        path = target.source_path
        if not path.exists():
            raise PdfInputError("PDF_NOT_FOUND", f"PDF 파일을 찾을 수 없습니다: {path}")
        if not path.is_file():
            raise PdfInputError("PDF_NOT_FILE", f"PDF 파일 경로가 아닙니다: {path}")
        if path.suffix.lower() != ".pdf":
            raise PdfInputError("PDF_EXTENSION_REQUIRED", f".pdf 파일만 지원합니다: {path}")
        try:
            size = path.stat().st_size
            with path.open("rb") as fp:
                head = fp.read(8)
        except OSError as exc:
            raise PdfInputError("PDF_UNREADABLE", f"PDF 파일을 읽을 수 없습니다: {path}: {exc}") from exc
        if size == 0:
            raise PdfInputError("PDF_EMPTY", f"PDF 파일이 0바이트입니다: {path}")
        if not has_valid_magic(head, ".pdf"):
            raise PdfInputError("INVALID_PDF_SIGNATURE", f"PDF 시그니처가 올바르지 않습니다: {path}")
        return target
