"""파일명/경로 정규화 유틸 (Windows 기준)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import unquote, urlparse

#: Windows 에서 파일/폴더 이름에 쓸 수 없는 문자
INVALID_CHARS = '\\/:*?"<>|'
_INVALID_RE = re.compile(r'[\\/:*?"<>|]')
# 탭/개행을 포함한 유니코드 공백과 파일명에 섞여 들어오는 BOM/zero-width
# space를 하나의 공백 run으로 취급한다. (나머지 제어문자는 별도 치환)
_WS_RE = re.compile(r"[\s\u200b\ufeff]+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")
_EXTENSION_RE = re.compile(r"\.[a-z0-9]{1,10}")

#: Windows 예약 파일명
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}


def _strip_storage_whitespace(text: str) -> str:
    """앞뒤 공백 run을 제거하고, 내부 run은 underscore 규칙으로 치환한다.

    원본 이름 ``A _123``의 공백은 오른쪽 이웃이 underscore이므로 제거되어
    ``A_123``이 된다. ``A B``처럼 양쪽에 underscore가 없는 run은 underscore
    하나로 바꾼다. 기존 underscore를 전역적으로 접지는 않는다.
    """
    text = _WS_RE.sub(
        lambda match: "" if (
            match.start() == 0
            or match.end() == len(text)
        ) else (
            "" if (
                text[match.start() - 1] == "_"
                or text[match.end()] == "_"
            ) else "_"
        ),
        text,
    )
    return text


def normalize_storage_component(name: str, replacement: str = "_", max_length: int = 120) -> str:
    """저장용 경로 구성요소를 Windows/공백 규칙에 맞게 정규화한다.

    이 함수의 결과만 파일/폴더 이름으로 사용한다. ``manifest``에는 호출
    전에 받은 원본 이름을 별도 필드로 보존해야 한다.

    - 사용 불가 문자(``\\ / : * ? " < > |``)와 제어문자를 replacement 로 치환
    - 내부 공백은 주변 underscore에 따라 제거하거나 underscore로 치환
    - 앞뒤 공백/마침표 제거 (Windows 는 끝의 '.'/' ' 를 허용하지 않음)
    - 예약어는 뒤에 '_' 를 붙여 회피
    - 빈 문자열이면 '_' 반환
    """
    if name is None:
        return "_"
    text = unicodedata.normalize("NFC", str(name))
    # 경계 공백은 제거하고 내부 공백은 원본 underscore와의 인접 여부를
    # 기준으로 처리한다. 이 단계는 invalid 문자 치환보다 먼저 수행하여
    # 원본의 이웃 관계를 보존한다.
    text = _strip_storage_whitespace(text)
    text = _CONTROL_RE.sub(replacement, text)
    text = _INVALID_RE.sub(replacement, text)
    text = text.strip()
    text = text.rstrip(". ")
    if not text:
        return "_"
    if text.upper() in RESERVED_NAMES or text.upper().split(".")[0] in RESERVED_NAMES:
        text = text + "_"
    if len(text) > max_length:
        text = shorten(text, max_length)
    return text

def shorten(text: str, max_length: int) -> str:
    """길이를 줄이되 원본 구분이 가능하도록 해시 8자를 뒤에 붙인다."""
    if len(text) <= max_length:
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    keep = max(1, max_length - len(digest) - 1)
    return f"{text[:keep]}~{digest}"


def split_extension(filename: str) -> tuple[str, str]:
    """('약관_31073.pdf') -> ('약관_31073', '.pdf'). 확장자는 소문자."""
    if not filename:
        return "", ""
    filename = str(filename).strip()
    idx = filename.rfind(".")
    if idx <= 0:
        return filename, ""
    extension = normalize_extension(filename[idx:])
    if not extension:
        return filename, ""
    return filename[:idx], extension


def normalize_extension(extension: str) -> str:
    """확장자를 저장용으로 정규화하고 검증한다.

    ``.PDF``와 `` PDF ``는 ``.pdf``가 되며, 경로 구분자나 다중 점을 포함한
    값은 확장자로 취급하지 않는다.
    """
    value = str(extension or "").strip().lower()
    if not value:
        return ""
    if not value.startswith("."):
        value = "." + value
    return value if _EXTENSION_RE.fullmatch(value) else ""


def guess_extension(url: str = "", content_disposition: str = "", content_type: str = "") -> str:
    """응답 정보로부터 확장자를 추정한다. 실패 시 빈 문자열.

    ``/cYakgwanDown.do?FilePath=InsProduct/약관.pdf`` 처럼 경로 확장자(.do)와 실제
    파일 확장자(.pdf)가 다른 사이트가 있으므로 URL 은 filename_from_url() 로 해석한다.
    """
    candidates = [
        filename_from_content_disposition(content_disposition),
        filename_from_url(url) if url else "",
        unquote(urlparse(url).path).rsplit("/", 1)[-1] if url else "",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        _, ext = split_extension(candidate.split("?")[0])
        if ext:
            return ext
    ct = (content_type or "").split(";")[0].strip().lower()
    return {
        "application/pdf": ".pdf",
        "application/x-pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/zip": ".zip",
        "application/x-zip-compressed": ".zip",
        "application/haansofthwp": ".hwp",
        "application/x-hwp": ".hwp",
        "application/vnd.hancom.hwp": ".hwp",
        "application/vnd.hancom.hwpx": ".hwpx",
    }.get(ct, "")


def filename_from_content_disposition(header: str) -> str:
    """Content-Disposition 헤더에서 파일명을 추출한다 (RFC5987 포함)."""
    if not header:
        return ""
    m = re.search(r"filename\*\s*=\s*([^;]+)", header, re.I)
    if m:
        value = m.group(1).strip().strip('"')
        if "''" in value:
            value = value.split("''", 1)[1]
        return unquote(value).strip()
    m = re.search(r'filename\s*=\s*"([^"]+)"', header, re.I)
    if not m:
        m = re.search(r"filename\s*=\s*([^;]+)", header, re.I)
    if not m:
        return ""
    return unquote(m.group(1).strip().strip('"').rstrip(";")).strip()


def filename_from_url(url: str) -> str:
    """URL 에서 파일명을 추출한다.

    ``/CG802030003.ec?fileNm=20260101_10101_1.pdf`` 처럼 경로가 아니라 쿼리스트링에
    실제 파일명이 들어 있는 사이트가 있으므로 쿼리 파라미터를 먼저 확인한다.
    """
    if not url:
        return ""
    parsed = urlparse(url)
    m = re.search(r"(?:fileNm|FilePath|fileName|file)=([^&]+)", parsed.query, re.I)
    if m:
        candidate = unquote(m.group(1)).rsplit("/", 1)[-1]
        if candidate:
            return candidate
    return unquote(parsed.path).rsplit("/", 1)[-1]
