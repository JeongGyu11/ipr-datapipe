"""문서 및 다운로드 상태 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class DocumentType:
    """저장 문서유형."""

    POLICY = "POLICY"          # 약관
    SUMMARY = "SUMMARY"        # 상품요약서
    METHOD = "METHOD"          # 사업방법서
    UNKNOWN = "UNKNOWN_DOCUMENT_TYPE"

    #: 문서유형 -> 저장 폴더명 / 파일명에 쓰이는 한글 표기
    FOLDER_NAME = {
        POLICY: "약관",
        SUMMARY: "상품요약서",
        METHOD: "사업방법서",
        UNKNOWN: "미분류",
    }

    ALL_COLLECTED = (POLICY, SUMMARY, METHOD)


class DownloadStatus:
    """manifest 의 download_status 값."""

    SUCCESS = "SUCCESS"
    DUPLICATE_SKIPPED = "DUPLICATE_SKIPPED"
    NO_DOCUMENT_LINK = "NO_DOCUMENT_LINK"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    INVALID_FILE = "INVALID_FILE"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    ACCESS_DENIED = "ACCESS_DENIED"
    UNKNOWN_DOCUMENT_TYPE = "UNKNOWN_DOCUMENT_TYPE"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    DRY_RUN = "DRY_RUN"

    #: 재시도(--retry-failed) 대상 상태
    RETRYABLE = (
        INVALID_RESPONSE,
        INVALID_FILE,
        DOWNLOAD_FAILED,
        ACCESS_DENIED,
    )
    #: 이미 처리 완료로 간주하는 상태
    COMPLETED = (SUCCESS, DUPLICATE_SKIPPED)


@dataclass
class Document:
    """상품 버전에 연결된 문서 1건."""

    document_type: str
    document_label: str                     # 사이트에 표시된 원본 문서명
    document_url: str = ""                  # 실제 다운로드 URL (없으면 빈 문자열)
    original_filename: str = ""             # 사이트가 제공하는 원본 파일명
    #: 어댑터별 다운로드 부가정보(예: 메리츠 암호화 토큰). 다운로드 방식이 URL 이 아닐 때 사용.
    download_hint: dict[str, Any] = field(default_factory=dict)
    #: fetch/redirect 결과와 무관한 원본 문서 위치 식별자.
    #: URL 없는 POST 문서는 어댑터가 비밀값 없는 locator를 제공한다.
    source_locator: str = ""

    @property
    def has_link(self) -> bool:
        return bool(self.document_url) or bool(self.download_hint)
