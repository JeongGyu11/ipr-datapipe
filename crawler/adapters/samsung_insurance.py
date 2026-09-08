"""삼성화재 Adapter.

수집 방식: 공시실 화면이 호출하는 JSON API 재현 (SITE_ANALYSIS.md §5)
  - 목록: POST /vh/data/VH.HDIF0103.do  (header={"tranId":"VH.HDIF0103"})
    → responseMessage.body.data.list 에 전체 상품 버전(약 9,400건)
  - 문서: GET https://www.samsungfire.com{prdfilenameN}
"""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import quote

from crawler.base_adapter import BaseInsurerAdapter
from crawler.http_client import AccessDeniedError
from models.product_version import ProductVersion
from utils.date_utils import is_open_ended, overlaps_month, parse_date

BASE = "https://www.samsungfire.com"
TRAN_ID = "VH.HDIF0103"
LIST_URL = f"{BASE}/vh/data/{TRAN_ID}.do"

#: 응답 필드 -> 화면 표시명 (IH_IF_Terms.js 의 pdfCnt 분기로 확인)
DOC_FIELDS = [
    ("prdfilename1", "보험약관"),
    ("prdfilename2", "사업방법서"),
    ("prdfilename3", "상품요약서"),
    ("prdfilename4", "상품설명서"),   # 기본 제외 대상
]


class SamsungInsuranceAdapter(BaseInsurerAdapter):
    code = "SAMSUNG"
    collection_method = "1순위 - 공시실 화면 JSON API 재현 (VH.HDIF0103 전량 조회)"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        self.stats["status_coverage_complete"] = False
        rows = self._fetch_list()
        self.log.info("[SAMSUNG] 전체 상품 버전 %d건 수신", len(rows))
        self.stats["api_rows"] = len(rows)
        self.stats["raw_rows"] = len(rows)
        versions: list[ProductVersion] = []
        filtered = 0
        unknown = 0
        for row in rows:
            sale_start = parse_date(row.get("saleStDt"))
            sale_end = parse_date(row.get("saleEnDt"))
            if sale_start is None:
                unknown += 1
            product_code = str(row.get("prdCode") or "")
            jong_gb = str(row.get("jongGb") or "")
            source_product_id = f"{product_code}_{jong_gb}" if jong_gb else product_code
            active_match = bool(self._active_status_rows) and self.matches_active_status_reference(
                source_product_id=source_product_id,
                product_name=row.get("prdName"),
                sale_start_date=sale_start,
            )
            if not (
                self._is_candidate(sale_start, sale_end, start_date, end_date)
                or active_match
            ):
                filtered += 1
                continue
            versions.append(self._to_version(row))
        self.stats["materialized_rows"] = len(versions)
        self.stats["filtered_rows"] = filtered
        self.stats["unknown_dates"] = unknown
        self.stats["status_coverage_complete"] = True
        return versions

    def _is_candidate(
        self,
        sale_start: date | None,
        sale_end: date | None,
        start_date: date | None,
        end_date: date | None,
    ) -> bool:
        # 날짜 범위를 직접 지정하지 않는 내부/하위호환 호출은 기존처럼
        # 전체 행을 materialize 한다.
        if start_date is None or end_date is None:
            return True
        mode = str(getattr(self.config, "date_selection_mode", "new_or_revised") or "new_or_revised")
        # 시작일을 알 수 없는 행은 공통 selector의 수동검토 대상으로
        # 남겨야 하므로 종료일만 보고 목록 단계에서 제거하지 않는다.
        if sale_start is None:
            return True
        if mode == "overlap":
            return overlaps_month(sale_start, sale_end, start_date, end_date)
        if mode != "new_or_revised":
            raise ValueError(f"알 수 없는 date_selection.mode: {mode!r}")
        # 날짜 미상은 버리지 않고 공통 selector가 수동검토로 남긴다.
        return start_date <= sale_start <= end_date

    # ------------------------------------------------------------------
    def _fetch_list(self) -> list[dict]:
        header = json.dumps({"tranId": TRAN_ID}, ensure_ascii=False)
        body = "header=" + quote(header)
        response = self.client.post(
            LIST_URL,
            content=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=max(self.config.timeout, 120),
        )
        if response.status_code == 403:
            raise AccessDeniedError("삼성화재 목록 HTTP 403")
        if response.status_code != 200:
            raise RuntimeError(f"삼성화재 목록 HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            raise RuntimeError("삼성화재 목록 응답 JSON 해석 실패") from None
        if not isinstance(payload, dict):
            raise RuntimeError("삼성화재 목록 응답 envelope가 객체가 아닙니다")

        # 응답 봉투: responseMessage.body.data.list
        response_message = payload.get("responseMessage")
        if response_message is not None and not isinstance(response_message, dict):
            raise RuntimeError("삼성화재 목록 responseMessage 구조가 잘못되었습니다")
        body_part = (response_message or {}).get("body") if response_message is not None else payload.get("body")
        if not isinstance(body_part, dict):
            raise RuntimeError("삼성화재 목록 body가 누락되었거나 객체가 아닙니다")
        if body_part.get("result") != "S":
            raise RuntimeError(f"삼성화재 목록 result 실패: {body_part.get('result')!r}")
        data = body_part.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("삼성화재 목록 data가 누락되었거나 객체가 아닙니다")
        rows = data.get("list")
        if not isinstance(rows, list):
            raise RuntimeError("삼성화재 목록 list가 누락되었거나 배열이 아닙니다")
        if any(not isinstance(row, dict) for row in rows):
            raise RuntimeError("삼성화재 목록 list 항목이 객체가 아닙니다")
        return rows

    # ------------------------------------------------------------------
    def _to_version(self, row: dict) -> ProductVersion:
        sale_start = parse_date(row.get("saleStDt"))
        sale_end_raw = row.get("saleEnDt")
        sale_end = parse_date(sale_end_raw)
        display_gb = str(row.get("displayGb") or "0")

        # displayGb 1=판매중 고정, 2=판매중지 고정, 그 외는 판매종료일로 판정
        if display_gb == "1":
            on_sale = True
        elif display_gb == "2":
            on_sale = False
        else:
            on_sale = is_open_ended(sale_end_raw)

        category = " / ".join(
            x for x in (str(row.get("prdGun") or ""), str(row.get("prdGb") or "")) if x
        )
        product_code = str(row.get("prdCode") or "")
        jong_gb = str(row.get("jongGb") or "")

        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=str(row.get("prdName") or "").strip(),
            product_category=category,
            source_product_id=f"{product_code}_{jong_gb}" if jong_gb else product_code,
            sale_status="판매중" if on_sale else "판매중지",
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=self.base_url,
            extra={"saleChannel": row.get("saleChannel", "")},
        )
        if sale_start:
            version.version_key = f"{sale_start:%Y%m%d}_판매개시"

        for field_name, label in DOC_FIELDS:
            path = str(row.get(field_name) or "").strip()
            if not path:
                continue
            url = path if path.startswith("http") else BASE + path
            document = self.make_document(
                label=label,
                url=url,
                filename=path.rsplit("/", 1)[-1],
            )
            if document is not None:
                version.documents.append(document)
        return version
