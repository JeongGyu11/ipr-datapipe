"""다운로드 응답/파일 검증 및 문서유형 판별."""

from __future__ import annotations

from dataclasses import dataclass

from models.document import DocumentType, DownloadStatus
from utils.network_io import strict_exists

#: HTML 오류 페이지 판별용 시그니처
_HTML_MARKERS = (b"<!doctype html", b"<html", b"<head", b"<script", b"<br>", b"<meta")

# 한/글 3.x 공개 형식의 30바이트 파일 인식 정보(한컴 HWP 형식 문서 §3.1).
# HWP 5.x 이상은 OLE Compound File 헤더를 사용하므로 두 형식을 모두
# 허용하되, 3.x는 짧은 ``HWP Docu`` 접두사가 아닌 전체 고정 시그니처를
# 요구한다.
HWP3_MAGIC = b"HWP Document File V3.00 \x1a\x01\x02\x03\x04\x05"

#: 확장자별 파일 시그니처(매직넘버)
_MAGIC = {
    ".pdf": (b"%PDF-",),
    ".zip": (b"PK\x03\x04", b"PK\x05\x06"),
    ".hwpx": (b"PK\x03\x04", b"PK\x05\x06"),
    ".docx": (b"PK\x03\x04", b"PK\x05\x06"),
    ".hwp": (b"\xd0\xcf\x11\xe0", HWP3_MAGIC),  # HWP 5.x OLE / HWP 3.x
    ".doc": (b"\xd0\xcf\x11\xe0",),
}


@dataclass
class ValidationResult:
    ok: bool
    status: str = ""          # 실패 시 DownloadStatus 값
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


def looks_like_html(data: bytes) -> bool:
    """응답 본문이 HTML(오류 페이지)인지."""
    head = data[:2048].lstrip().lower()
    return any(head.startswith(m) or m in head[:512] for m in _HTML_MARKERS)


def has_valid_magic(data: bytes, extension: str) -> bool:
    """확장자에 맞는 파일 시그니처를 갖고 있는지.

    시그니처를 모르는 확장자는 True 로 통과시킨다(형식 그대로 보존).
    """
    signatures = _MAGIC.get((extension or "").lower())
    if not signatures:
        return True
    return any(data.startswith(sig) for sig in signatures)


def _magic_read_length(extension: str) -> int:
    """저장 파일 헤더 재검증에 필요한 최소 읽기 길이."""

    signatures = _MAGIC.get((extension or "").lower())
    if not signatures:
        return 8
    return max(8, max(len(signature) for signature in signatures))


def validate_response(
    *,
    status_code: int,
    content_type: str,
    data: bytes,
    extension: str,
    allowed_content_types: set[str],
    allowed_extensions: set[str],
) -> ValidationResult:
    """요구사항 §11 의 검증 항목을 순서대로 확인한다."""

    # 1) HTTP 상태 코드
    if status_code == 403:
        return ValidationResult(False, DownloadStatus.ACCESS_DENIED, "HTTP 403 (접근 거부)")
    if status_code != 200:
        return ValidationResult(False, DownloadStatus.INVALID_RESPONSE, f"HTTP {status_code}")

    # 3) 파일 크기가 0바이트가 아닌지
    if not data:
        return ValidationResult(False, DownloadStatus.INVALID_FILE, "응답 본문이 0바이트")

    # 4) HTML 오류 페이지가 저장되지 않았는지
    if looks_like_html(data):
        snippet = data[:200].decode("utf-8", "replace").replace("\n", " ").strip()
        if "firewall" in snippet.lower() or "차단" in snippet:
            return ValidationResult(False, DownloadStatus.ACCESS_DENIED, f"웹방화벽 차단 응답: {snippet[:120]}")
        return ValidationResult(False, DownloadStatus.INVALID_RESPONSE, f"HTML 응답 수신: {snippet[:120]}")

    ext = (extension or "").lower()

    # 확장자 허용 목록
    if ext and ext not in allowed_extensions:
        return ValidationResult(False, DownloadStatus.INVALID_FILE, f"허용되지 않은 확장자: {ext}")

    # 2) Content-Type 확인 (헤더가 없거나 부정확한 사이트가 있어 시그니처와 함께 판단)
    ct = (content_type or "").split(";")[0].strip().lower()
    ct_ok = (not ct) or ct in allowed_content_types

    # 5) 파일 헤더 검증
    magic_ok = has_valid_magic(data, ext)

    if not magic_ok:
        return ValidationResult(
            False,
            DownloadStatus.INVALID_FILE,
            f"파일 시그니처 불일치 (ext={ext}, head={data[:8]!r})",
        )
    if not ct_ok and ext not in _MAGIC:
        # 시그니처로도 확인할 수 없고 Content-Type 도 허용목록 밖이면 실패 처리
        return ValidationResult(False, DownloadStatus.INVALID_RESPONSE, f"허용되지 않은 Content-Type: {ct}")

    return ValidationResult(True)


def validate_saved_file(path, expected_size: int, extension: str) -> ValidationResult:
    """저장 후 파일을 실제로 열어 크기/시그니처를 재확인한다(§11-6)."""
    from pathlib import Path

    p = Path(path)
    # ``Path.exists``는 SMB stat 오류를 False로 삼킬 수 있어 네트워크 일시
    # 장애가 단순한 파일 부재 검증 결과로 변하지 않도록 strict stat을 쓴다.
    if not strict_exists(p):
        return ValidationResult(False, DownloadStatus.INVALID_FILE, "저장된 파일이 존재하지 않음")
    size = p.stat().st_size
    if size == 0:
        return ValidationResult(False, DownloadStatus.INVALID_FILE, "저장된 파일이 0바이트")
    if expected_size and size != expected_size:
        return ValidationResult(False, DownloadStatus.INVALID_FILE, f"파일 크기 불일치 ({size} != {expected_size})")
    try:
        with open(p, "rb") as fp:
            # HWP 3.x의 인식 정보는 30바이트이므로 고정 8바이트만
            # 읽으면 response 단계에서 통과한 정상 파일을 오탐한다.
            head = fp.read(_magic_read_length(extension))
    except OSError as exc:
        return ValidationResult(False, DownloadStatus.INVALID_FILE, f"파일을 열 수 없음: {exc}")
    if not has_valid_magic(head, extension):
        return ValidationResult(False, DownloadStatus.INVALID_FILE, "저장 파일 시그니처 불일치")
    return ValidationResult(True)


# ----------------------------------------------------------------------
# 문서유형 판별
# ----------------------------------------------------------------------
class DocumentClassifier:
    """사이트 표시명 -> 저장 문서유형."""

    def __init__(self, document_types: dict[str, list[str]], exclude_keywords: list[str]):
        # 긴 키워드를 먼저 매칭해야 '상품요약서' 가 '약관' 보다 우선한다.
        self._rules: list[tuple[str, str]] = []
        for key, type_name in (
            ("policy", DocumentType.POLICY),
            ("summary", DocumentType.SUMMARY),
            ("method", DocumentType.METHOD),
        ):
            for keyword in document_types.get(key, []):
                self._rules.append((str(keyword), type_name))
        self._rules.sort(key=lambda kv: len(kv[0]), reverse=True)
        self._exclude = [str(k) for k in exclude_keywords]

    def is_excluded(self, label: str) -> bool:
        """기본 수집 대상에서 제외되는 자료인지."""
        text = _normalize(label)
        return any(_normalize(k) in text for k in self._exclude)

    def classify(self, label: str, filename: str = "") -> str:
        """표시명(우선) 또는 파일명으로 문서유형을 판별한다."""
        for source in (label, filename):
            text = _normalize(source)
            if not text:
                continue
            for keyword, type_name in self._rules:
                if _normalize(keyword) in text:
                    return type_name
        return DocumentType.UNKNOWN


def _normalize(text: str) -> str:
    return "".join(str(text or "").split()).lower()
