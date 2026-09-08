"""다운로드 응답 검증 / PDF 헤더 / SHA-256 중복 판정 테스트."""

from pathlib import Path

import pytest

from crawler.validators import (
    HWP3_MAGIC,
    has_valid_magic,
    looks_like_html,
    validate_response,
    validate_saved_file,
)
from models.document import DownloadStatus
from utils.hash_utils import sha256_bytes, sha256_file

FIXTURES = Path(__file__).parent / "fixtures"

ALLOWED_CT = {"application/pdf", "application/octet-stream", "application/zip"}
ALLOWED_EXT = {".pdf", ".hwp", ".hwpx", ".doc", ".docx", ".zip"}


def read_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def ok(data: bytes, ext=".pdf", ct="application/pdf", status=200):
    return validate_response(
        status_code=status,
        content_type=ct,
        data=data,
        extension=ext,
        allowed_content_types=ALLOWED_CT,
        allowed_extensions=ALLOWED_EXT,
    )


# 7. HTML 오류 응답 검출 -------------------------------------------------------
def test_detects_html_error_page():
    html = read_fixture("error_page.html")
    assert looks_like_html(html) is True
    result = ok(html)
    assert not result
    assert result.status == DownloadStatus.INVALID_RESPONSE


def test_detects_firewall_block_as_access_denied():
    blocked = read_fixture("firewall_blocked.html")
    result = ok(blocked)
    assert not result
    assert result.status == DownloadStatus.ACCESS_DENIED


def test_pdf_is_not_html():
    assert looks_like_html(read_fixture("sample.pdf")) is False


# 8. PDF 헤더 검증 -------------------------------------------------------------
def test_valid_pdf_passes():
    assert ok(read_fixture("sample.pdf")) is not None
    assert ok(read_fixture("sample.pdf")).ok is True


def test_pdf_without_magic_header_fails():
    result = ok(b"NOTPDF" + b"\x00" * 100)
    assert not result
    assert result.status == DownloadStatus.INVALID_FILE
    assert "시그니처" in result.reason


@pytest.mark.parametrize(
    "data,ext,expected",
    [
        (b"%PDF-1.7\n", ".pdf", True),
        (b"XXXX", ".pdf", False),
        (b"PK\x03\x04rest", ".zip", True),
        (b"PK\x03\x04rest", ".hwpx", True),
        (b"PK\x03\x04rest", ".docx", True),
        (b"\xd0\xcf\x11\xe0abcd", ".hwp", True),
        (HWP3_MAGIC + b"body", ".hwp", True),
        (b"HWP Document File V3.00 ", ".hwp", False),
        (b"HWP Document File V3.00 \x1a\x01\x02\x03\x04", ".hwp", False),
        (b"PK\x03\x04rest", ".hwp", False),
        (b"anything", ".unknown", True),   # 시그니처를 모르는 확장자는 통과
    ],
)
def test_has_valid_magic(data, ext, expected):
    assert has_valid_magic(data, ext) is expected


# HTTP 상태 / 크기 / 확장자 ----------------------------------------------------
def test_non_200_is_invalid_response():
    result = ok(read_fixture("sample.pdf"), status=500)
    assert result.status == DownloadStatus.INVALID_RESPONSE


def test_403_is_access_denied():
    result = ok(read_fixture("sample.pdf"), status=403)
    assert result.status == DownloadStatus.ACCESS_DENIED


def test_zero_byte_is_invalid_file():
    result = ok(b"")
    assert result.status == DownloadStatus.INVALID_FILE


def test_disallowed_extension_rejected():
    result = ok(read_fixture("sample.pdf"), ext=".exe")
    assert result.status == DownloadStatus.INVALID_FILE
    assert "확장자" in result.reason


def test_hwp_is_preserved_not_rejected():
    """PDF 가 아닌 HWP 도 원본 형식 그대로 허용한다."""
    result = ok(b"\xd0\xcf\x11\xe0" + b"\x00" * 64, ext=".hwp", ct="application/x-hwp")
    assert result.ok is True


def test_hwp3_signature_is_accepted_and_html_like_body_is_rejected():
    assert len(HWP3_MAGIC) == 30
    result = ok(HWP3_MAGIC + b"\x00" * 64, ext=".hwp", ct="application/x-hwp")
    assert result.ok is True

    # A valid header followed by an HTML error page must still be rejected by
    # the response validator's HTML guard.
    html = HWP3_MAGIC + b"<html><body>error</body></html>"
    result = ok(html, ext=".hwp", ct="application/x-hwp")
    assert result.status == DownloadStatus.INVALID_RESPONSE


# 저장 후 검증 -----------------------------------------------------------------
def test_validate_saved_file(tmp_path):
    data = read_fixture("sample.pdf")
    path = tmp_path / "a.pdf"
    path.write_bytes(data)
    assert validate_saved_file(path, len(data), ".pdf").ok is True


def test_validate_saved_hwp3_file_reads_full_magic(tmp_path):
    data = HWP3_MAGIC + b"\x00" * 64
    path = tmp_path / "legacy.hwp"
    path.write_bytes(data)
    assert validate_saved_file(path, len(data), ".hwp").ok is True


def test_validate_saved_hwp3_truncated_magic_fails(tmp_path):
    data = HWP3_MAGIC[:-1]
    path = tmp_path / "truncated.hwp"
    path.write_bytes(data)
    result = validate_saved_file(path, len(data), ".hwp")
    assert result.status == DownloadStatus.INVALID_FILE
    assert "시그니처" in result.reason


def test_validate_saved_ole_hwp_file_remains_supported(tmp_path):
    data = b"\xd0\xcf\x11\xe0" + b"\x00" * 64
    path = tmp_path / "ole.hwp"
    path.write_bytes(data)
    assert validate_saved_file(path, len(data), ".hwp").ok is True


def test_validate_saved_file_size_mismatch(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF-1.4 short")
    result = validate_saved_file(path, 9999, ".pdf")
    assert result.status == DownloadStatus.INVALID_FILE


def test_validate_saved_file_missing(tmp_path):
    result = validate_saved_file(tmp_path / "missing.pdf", 10, ".pdf")
    assert result.status == DownloadStatus.INVALID_FILE


# 6. SHA-256 중복 판정 ---------------------------------------------------------
def test_sha256_file_matches_in_memory_digest(tmp_path):
    data = read_fixture("sample.pdf")
    path = tmp_path / "a.pdf"
    path.write_bytes(data)

    assert sha256_file(path) == sha256_bytes(data)


def test_sha256_differs_for_different_content():
    assert sha256_bytes(b"a") != sha256_bytes(b"b")
