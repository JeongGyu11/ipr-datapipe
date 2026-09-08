"""KB라이프생명 Adapter.

수집 방식: JSON_API (docs/sites/KB_LIFE.md)
  - 목록: POST /customer-common/API/productList1.do
          {pageSize, paGroupCnt, pageIndex, tabType(1=판매/2=판매중지), srchType, pdNm}
  - 문서: GET /api/archive/archives/download/{fileno}/{SEQNO}/{boxno}
          매핑은 화면 스크립트 productList.js 의 분기에서 확인:
            UPFILE  -> 요약서   product-explain / 0
            UPFILE1 -> 방법서   product-explain / 1
            UPFILE2 -> 약관     product-terms   / 2
            UPFILE3 -> 약관     product-terms   / 8
            UPFILE4 -> 약관     product-terms   / 9
            UPFILE5 -> 상품설명서(수집 제외 대상) product-explain / 100
"""

from __future__ import annotations

from datetime import date

from crawler.adapters.common import parse_period
from crawler.base_adapter import BaseInsurerAdapter
from models.product_version import ProductVersion
from utils.date_utils import parse_date

BASE = "https://www.kblife.co.kr"
LIST_URL = f"{BASE}/customer-common/API/productList1.do"
PAGE_URL = f"{BASE}/customer-common/productList.do"
DOWNLOAD_URL = f"{BASE}/api/archive/archives/download"

#: 응답 필드 -> (화면 표시명, fileno, boxno)
DOC_FIELDS = [
    ("UPFILE", "상품요약서", "product-explain", "0"),
    ("UPFILE1", "사업방법서", "product-explain", "1"),
    ("UPFILE2", "약관", "product-terms", "2"),
    ("UPFILE3", "약관", "product-terms", "8"),
    ("UPFILE4", "약관", "product-terms", "9"),
    ("UPFILE5", "상품설명서", "product-explain", "100"),   # 기본 제외 대상
]

TABS = [("1", "판매중"), ("2", "판매중지")]


class KBLifeAdapter(BaseInsurerAdapter):
    code = "KB_LIFE"
    collection_method = "JSON_API - productList1.do 탭별 페이지네이션 전량 조회"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        versions: list[ProductVersion] = []
        for tab, status in TABS:
            versions.extend(self._collect_tab(tab, status))
        self.log.info("[KB_LIFE] 상품 버전 %d건 수집", len(versions))
        self.stats["api_rows"] = len(versions)
        return versions

    # ------------------------------------------------------------------
    def _collect_tab(self, tab: str, status: str) -> list[ProductVersion]:
        out: list[ProductVersion] = []
        page = 1
        last_page = 1
        while page <= last_page:
            payload = {
                "pageSize": "100",
                "paGroupCnt": "10",
                "pageIndex": str(page),
                "tabType": tab,
                "srchType": "",
                "pdNm": "",
            }
            response = self.client.post(LIST_URL, data=payload, headers={"Referer": PAGE_URL})
            if response.status_code != 200:
                self.log.warning("[KB_LIFE] tab=%s page=%d 조회 실패 HTTP %d", tab, page, response.status_code)
                break
            try:
                data = response.json()
            except ValueError:
                self.log.warning("[KB_LIFE] tab=%s page=%d JSON 해석 실패", tab, page)
                break
            paging = data.get("pagingVO") or {}
            last_page = int(paging.get("finalPgNo") or 1)
            rows = data.get("list") or []
            for row in rows:
                version = self._to_version(row, status)
                if version is not None:
                    out.append(version)
            self.log.info("[KB_LIFE] tab=%s page=%d/%d rows=%d", tab, page, last_page, len(rows))
            if not rows:
                break
            page += 1
        return out

    def _to_version(self, row: dict, status: str) -> ProductVersion | None:
        name = str(row.get("NAME") or "").strip()
        if not name:
            return None
        sale_start, sale_end = parse_period(str(row.get("SALE_DATE") or ""))
        if sale_end is None:
            sale_end = parse_date(row.get("PROD_SALE_END_DATE"))
        seq_no = str(row.get("SEQNO") or "")

        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=name,
            product_category=str(row.get("TYPE") or ""),
            source_product_id=f"{row.get('P_CODE') or ''}_{seq_no}".strip("_"),
            sale_status="판매중지" if sale_end else status,
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=PAGE_URL,
            extra={"seqNo": seq_no, "perType": row.get("PER_TYPE", "")},
        )
        if sale_start:
            version.version_key = f"{sale_start:%Y%m%d}_판매개시"

        for field, label, fileno, boxno in DOC_FIELDS:
            path = str(row.get(field) or "").strip()
            if not path:
                continue
            doc = self.make_document(
                label=label,
                url=f"{DOWNLOAD_URL}/{fileno}/{seq_no}/{boxno}",
                filename=path.rsplit("/", 1)[-1],
            )
            if doc is not None:
                version.documents.append(doc)
        return version
