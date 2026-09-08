"""상품 버전 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .document import Document
from .sale_status import SaleStatus, classify_sale_status


class DateBasis:
    """월 필터에 사용한 날짜의 종류 (요구사항 §6 우선순위)."""

    REVISION_DATE = "revision_date"          # 1순위: 문서 적용일/개정일
    SALE_START_DATE = "sale_start_date"      # 2순위: 상품 판매개시일
    DISCLOSURE_DATE = "disclosure_date"      # 3순위: 공시일/등록일
    SALE_PERIOD_START = "sale_period_start"  # 4순위: 판매기간 시작일
    NONE = "NONE"                            # 날짜 없음 -> MANUAL_REVIEW_REQUIRED


@dataclass
class ProductVersion:
    """공시실에서 조회한 상품 버전 1건."""

    company_code: str
    company_name: str
    product_name_raw: str
    source_page_url: str
    # Catalog의 불변 저장 폴더 식별자. 표시명(company_name)과 분리한다.
    storage_name: str = ""

    product_category: str = ""
    source_product_id: str = ""
    version_key: str = ""            # 폴더명에 쓰이는 버전/판매기간 표기
    sale_status: str = ""            # 사이트 원문(예: "판매중" / "판매중지"); 경로는 normalized_sale_status 사용

    sale_start_date: date | None = None
    sale_end_date: date | None = None
    disclosure_date: date | None = None
    revision_date: date | None = None

    documents: list[Document] = field(default_factory=list)
    #: 어댑터가 남기는 부가정보(다운로드 시 필요한 세션 데이터 등)
    extra: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # 요구사항 §6 - 날짜 우선순위
    # ------------------------------------------------------------------
    @property
    def target_date(self) -> date | None:
        """월 필터에 사용할 날짜."""
        return self.revision_date or self.sale_start_date or self.disclosure_date

    @property
    def date_basis(self) -> str:
        """어떤 종류의 날짜를 사용했는지."""
        if self.revision_date:
            return DateBasis.REVISION_DATE
        if self.sale_start_date:
            return DateBasis.SALE_START_DATE
        if self.disclosure_date:
            return DateBasis.DISCLOSURE_DATE
        return DateBasis.NONE

    @property
    def needs_manual_review(self) -> bool:
        """날짜가 전혀 없어 자동 판단이 불가능한 경우."""
        return self.target_date is None

    @property
    def normalized_sale_status(self) -> SaleStatus:
        """파일 시스템 경로에서 사용할 정규화 판매 상태.

        ``sale_status`` 원문은 manifest/checkpoint에 그대로 보존하고, 이
        프로퍼티의 값만 저장 경로 계산에 사용한다.
        """
        explicit = self.extra.get("sale_status_normalized") if isinstance(self.extra, dict) else None
        return classify_sale_status(
            self.sale_status,
            explicit_status=explicit,
            sale_end_date=self.sale_end_date,
        )

    def resolved_version_key(self) -> str:
        """폴더명으로 쓸 버전 키. 확인 불가 시 UNKNOWN_VERSION."""
        if self.version_key:
            return self.version_key
        if self.sale_start_date:
            return f"{self.sale_start_date:%Y%m%d}_판매개시"
        return "UNKNOWN_VERSION"
