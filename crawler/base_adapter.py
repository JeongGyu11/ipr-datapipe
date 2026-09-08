"""보험사 Adapter 공통 인터페이스."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping

from crawler.company_catalog import CompanyDefinition
from crawler.config import AppConfig
from crawler.http_client import AccessDeniedError, HttpClient
from crawler.validators import DocumentClassifier
from models.document import Document, DownloadStatus
from models.product_version import ProductVersion
from utils.file_utils import filename_from_content_disposition, filename_from_url, normalize_storage_component
from utils.crawler_logger import get_logger


@dataclass
class FetchResult:
    """문서 1건을 메모리로 받아온 결과."""

    ok: bool
    status: str = DownloadStatus.SUCCESS
    content: bytes = b""
    content_type: str = ""
    original_filename: str = ""
    http_status: int = 0
    reason: str = ""
    final_url: str = ""


class BaseInsurerAdapter:
    """모든 보험사 Adapter 의 공통 인터페이스.

    구현체는 최소한 collect_product_versions() 를 구현해야 한다.
    문서 링크가 목록 조회 단계에서 함께 오는 사이트는 collect_documents() 기본 구현을 그대로 쓴다.
    """

    #: 하위 클래스에서 지정
    code: str = ""
    name: str = ""

    def __init__(
        self,
        company: CompanyDefinition,
        config: AppConfig,
        classifier: DocumentClassifier,
        runtime_options: Mapping[str, object] | None = None,
    ):
        self.company = company
        self.config = config
        self.classifier = classifier
        # Catalog options are immutable policy. Per-run caps/overrides belong
        # to this mutable copy and must never mutate the shared definition.
        self.runtime_options = dict(runtime_options or company.options)
        self.log = get_logger()
        self.code = company.code
        self.name = company.name
        self.base_url = company.entry_url
        self.stats: dict[str, int | str | bool] = {}
        self._client: HttpClient | None = None
        self._active_status_rows: list[dict] = []

    # ------------------------------------------------------------------
    # 필수 인터페이스
    # ------------------------------------------------------------------
    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        """대상 기간의 상품 버전 목록을 수집한다."""
        raise NotImplementedError

    def collect_documents(self, product_version: ProductVersion) -> list[Document]:
        """상품 버전에 연결된 문서 목록을 돌려준다.

        대부분의 사이트는 목록 조회 시 문서 링크가 함께 오므로 기본 구현으로 충분하다.
        """
        return product_version.documents

    # ------------------------------------------------------------------
    # 판매중 상품 재검증 지원
    # ------------------------------------------------------------------
    def configure_active_status_refresh(self, rows: Iterable[Mapping]) -> None:
        """기존 manifest의 판매중 버전을 이번 목록 수집에 포함하도록 설정한다.

        기본 구현은 참조 행만 보관한다. 목록 단계에서 대상 기간을 미리
        거르는 어댑터는 :meth:`matches_active_status_reference`를 사용해 과거
        판매개시 버전도 materialize해야 한다. 네트워크 호출은 정상 수집과
        공유하므로 상태 확인을 위해 같은 목록을 두 번 요청하지 않는다.
        """

        self._active_status_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
        self.stats["active_status_requested"] = len(self._active_status_rows)

    @property
    def active_status_rows(self) -> list[dict]:
        """호출부가 설정한 판매중 manifest 행의 복사본."""

        return [dict(row) for row in self._active_status_rows]

    def matches_active_status_reference(
        self,
        *,
        source_product_id: object = "",
        product_name: object = "",
        sale_start_date: object = None,
        target_date: object = None,
    ) -> bool:
        """원시 목록 행/상품 버전이 기존 판매중 버전과 같은지 판정한다.

        source id가 양쪽에 있으면 이를 최우선으로 사용하고, 동일 id 안의
        여러 개정 버전은 판매개시일로 구분한다. id가 없는 사이트는 정규화
        상품명과 날짜를 조합한다. 후보 날짜가 아직 상세조회 전이라 비어
        있으면 보수적으로 포함하여 상태 갱신 누락을 막는다.
        """

        candidate_id = str(source_product_id or "").strip()
        candidate_name = normalize_storage_component(str(product_name or ""))
        candidate_start = self._status_date_key(sale_start_date)
        candidate_target = self._status_date_key(target_date)
        for row in self._active_status_rows:
            row_id = str(row.get("source_product_id") or "").strip()
            row_start = self._status_date_key(row.get("sale_start_date"))
            row_target = self._status_date_key(row.get("target_date"))
            if row_id and candidate_id:
                if row_id != candidate_id:
                    continue
                if row_start and candidate_start and row_start != candidate_start:
                    continue
                return True

            row_name = str(
                row.get("product_name_normalized")
                or normalize_storage_component(str(row.get("product_name_raw") or ""))
            )
            if not row_name or not candidate_name or row_name != candidate_name:
                continue
            if row_start and candidate_start and row_start != candidate_start:
                continue
            if not row_start and row_target and candidate_target and row_target != candidate_target:
                continue
            return True
        return False

    @staticmethod
    def _status_date_key(value: object) -> str:
        if isinstance(value, date):
            return value.isoformat()
        return str(value or "").strip()[:10]

    # ------------------------------------------------------------------
    # 공통 구현
    # ------------------------------------------------------------------
    @property
    def client(self) -> HttpClient:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self) -> HttpClient:
        return HttpClient(
            timeout=self.config.timeout,
            interval=self._interval(),
            max_concurrent=int(self.config.crawler.get("max_concurrent_requests_per_domain", 1)),
            max_retries=self.config.max_retries,
            backoff=self.config.retry_backoff,
            retry_status_codes=self.config.retry_status_codes,
            user_agent=self.config.user_agent,
            headers={"Referer": self.base_url} if self.base_url else None,
            legacy_ssl=self._legacy_ssl(),
        )

    def _legacy_ssl(self) -> bool:
        """구형 TLS 호환 컨텍스트 사용 여부.

        하위 클래스에서 ``legacy_ssl = True`` 로 지정하거나 config 의
        ``options.legacy_ssl`` 로 켤 수 있다. 기본값은 False 이므로 기존 5개사는 영향 없음.
        """
        override = self.runtime_options.get("legacy_ssl")
        if override is not None:
            return bool(override)
        return bool(getattr(type(self), "legacy_ssl", False))

    def _interval(self) -> float:
        """보험사별 요청 간격(설정으로 개별 조정 가능)."""
        override = self.runtime_options.get("request_interval_seconds")
        return float(override) if override is not None else self.config.request_interval

    def fetch_document(self, document: Document) -> FetchResult:
        """URL 기반 기본 다운로드 구현."""
        if not document.document_url:
            return FetchResult(False, DownloadStatus.NO_DOCUMENT_LINK, reason="문서 URL 없음")
        try:
            response = self.client.get(document.document_url)
        except AccessDeniedError as exc:
            return FetchResult(False, DownloadStatus.ACCESS_DENIED, reason=str(exc))
        except Exception as exc:  # noqa: BLE001 - 네트워크 계층 예외 전부 기록
            return FetchResult(False, DownloadStatus.DOWNLOAD_FAILED, reason=f"{type(exc).__name__}: {exc}")

        disposition = response.headers.get("content-disposition", "")
        original = (
            filename_from_content_disposition(disposition)
            or document.original_filename
            or filename_from_url(str(response.url))
        )
        return FetchResult(
            ok=response.status_code == 200,
            status=DownloadStatus.SUCCESS if response.status_code == 200 else DownloadStatus.INVALID_RESPONSE,
            content=response.content,
            content_type=response.headers.get("content-type", ""),
            original_filename=original,
            http_status=response.status_code,
            final_url=str(response.url),
        )

    # ------------------------------------------------------------------
    def open(self) -> None:
        """보험사 단위 리소스 준비(브라우저 기동 등)."""

    def close(self) -> None:
        """보험사 단위 리소스 정리."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "BaseInsurerAdapter":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------
    def make_document(
        self,
        label: str,
        url: str = "",
        filename: str = "",
        *,
        source_locator: str = "",
        **hint,
    ) -> Document | None:
        """표시명으로 문서유형을 판별해 Document 를 만든다.

        기본 제외 대상(상품설명서 등)이면 None 을 돌려준다.
        판별 불가 시에는 제외하지 않고 UNKNOWN_DOCUMENT_TYPE 으로 남긴다.
        """
        if self.classifier.is_excluded(label) or self.classifier.is_excluded(filename):
            return None
        doc_type = self.classifier.classify(label, filename)
        return Document(
            document_type=doc_type,
            document_label=label,
            document_url=url,
            original_filename=filename,
            download_hint=dict(hint),
            source_locator=source_locator,
        )
