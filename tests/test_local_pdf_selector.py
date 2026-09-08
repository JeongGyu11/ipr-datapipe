"""로컬 PDF 선택기의 경로·확장자·시그니처 검증."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.document_source.local_pdf import LocalPdfSelector, PdfInputError


def _target(path: Path):
    return LocalPdfSelector().select([path])[0]


def test_selector_accepts_uppercase_pdf_extension_and_korean_path(tmp_path: Path) -> None:
    source = tmp_path / "한글 상품약관.PDF"
    source.write_bytes(b"%PDF-1.7\ncontent")

    target = LocalPdfSelector.validate(_target(source))

    assert target.source_path == source.resolve()


@pytest.mark.parametrize(
    ("name", "content", "expected_code"),
    [
        ("문서.txt", b"%PDF-1.7\ncontent", "PDF_EXTENSION_REQUIRED"),
        ("빈문서.pdf", b"", "PDF_EMPTY"),
        ("HTML오류.pdf", b"<html>error</html>", "INVALID_PDF_SIGNATURE"),
    ],
)
def test_selector_rejects_invalid_pdf_inputs(
    tmp_path: Path,
    name: str,
    content: bytes,
    expected_code: str,
) -> None:
    source = tmp_path / name
    source.write_bytes(content)

    with pytest.raises(PdfInputError) as exc_info:
        LocalPdfSelector.validate(_target(source))

    assert exc_info.value.code == expected_code


def test_selector_rejects_directory(tmp_path: Path) -> None:
    directory = tmp_path / "directory.pdf"
    directory.mkdir()

    with pytest.raises(PdfInputError) as exc_info:
        LocalPdfSelector.validate(_target(directory))

    assert exc_info.value.code == "PDF_NOT_FILE"
