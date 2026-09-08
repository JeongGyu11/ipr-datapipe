"""NH농협생명 Adapter.

수집 방식: FORM_POST (docs/sites/NH_LIFE.md)
  - 목록: POST /ho/on/HOON0004M00.nhl
          {prsPagcn=페이지, useyn=Y|N, prodDcd=CTGR01~14, prodnm}
          페이지당 10행, 표 = 보험종류 / 상품명 / 판매여부 / 기간별 다운로드
  - 상세(팝업): POST /ho/on/HOON0004P10.nhl {selProdNm=상품명, …}
          → 표 = 판매기간 / 상품요약서 / 사업방법서 / 보험약관
            버튼 onclick="popupPdfViewer('<파일ID>','0|1|2')"
  - 문서: GET /pdfViewer.nhl?apdFlid=<파일ID>&fileSeqn=0|1|2
"""

from __future__ import annotations

import re
from datetime import date

from crawler.adapters.common import clean, parse_period, soup, table_rows
from crawler.base_adapter import BaseInsurerAdapter
from models.document import Document
from models.product_version import ProductVersion

BASE = "https://www.nhlife.co.kr"
PAGE_URL = f"{BASE}/ho/on/HOON0004M00.nhl"
POPUP_URL = f"{BASE}/ho/on/HOON0004P10.nhl"
VIEWER_URL = f"{BASE}/pdfViewer.nhl"

MODES = [("Y", "판매중"), ("N", "판매중지")]
#: fileSeqn -> 화면 표시명 (팝업 표 열 순서와 동일)
DOC_SEQN = [("0", "상품요약서"), ("1", "사업방법서"), ("2", "보험약관")]
MAX_PAGES = 300

_FILE_RE = re.compile(r"popupPdfViewer\('([^']+)'\s*,\s*'(\d+)'\)")


class NHLifeAdapter(BaseInsurerAdapter):
    code = "NH_LIFE"
    collection_method = "FORM_POST - HOON0004M00 목록 페이지네이션 + 상품별 기간 팝업"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        products: list[tuple[str, str, str, str]] = []   # (useyn, status, 보험종류, 상품명)
        for useyn, status in MODES:
            products.extend(self._collect_products(useyn, status))
        self.log.info("[NH_LIFE] 상품 %d건 수집, 팝업 조회 시작", len(products))
        self.stats["products"] = len(products)

        limit = self.runtime_options.get("max_products")
        if limit and len(products) > int(limit):
            self.stats["coverage_capped"] = True
            self.stats["products_total"] = len(products)
            self.stats["products_skipped"] = len(products) - int(limit)
            products = products[: int(limit)]

        versions: list[ProductVersion] = []
        for index, item in enumerate(products, start=1):
            versions.extend(self._collect_versions(*item))
            if index % 50 == 0:
                self.log.info("[NH_LIFE] 팝업 진행 %d/%d", index, len(products))
        self.log.info("[NH_LIFE] 상품 버전 %d건 수집", len(versions))
        return versions

    # ------------------------------------------------------------------
    def _collect_products(self, useyn: str, status: str) -> list[tuple[str, str, str, str]]:
        out: list[tuple[str, str, str, str]] = []
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            response = self.client.post(
                PAGE_URL,
                data={"prsPagcn": str(page), "useyn": useyn, "prodDcd": "", "prodnm": "", "selProdNm": ""},
                headers={"Referer": PAGE_URL},
            )
            if response.status_code != 200:
                self.log.warning("[NH_LIFE] useyn=%s page=%d 실패 HTTP %d", useyn, page, response.status_code)
                break
            rows = table_rows(soup(response.text).select_one("table"))
            fresh = 0
            for row in rows:
                headers = row.find_all("th")
                cells = row.find_all("td")
                if not headers or len(cells) < 2:
                    continue
                kind = clean(headers[0])
                name = clean(cells[0])
                if not name or name in seen:
                    continue
                seen.add(name)
                out.append((useyn, status, kind, name))
                fresh += 1
            if fresh == 0:
                break
        self.log.info("[NH_LIFE] useyn=%s -> 상품 %d건", useyn, len(out))
        return out

    def _collect_versions(self, useyn, status, kind, name) -> list[ProductVersion]:
        try:
            response = self.client.post(
                POPUP_URL,
                data={"prsPagcn": "1", "useyn": useyn, "prodDcd": "", "prodnm": "", "selProdNm": name},
                headers={"Referer": PAGE_URL, "X-Requested-With": "XMLHttpRequest"},
            )
        except Exception as exc:  # noqa: BLE001
            self.log.warning("[NH_LIFE] 팝업 실패(%s): %s", name, exc)
            return []
        if response.status_code != 200:
            return []

        out: list[ProductVersion] = []
        for row in table_rows(soup(response.text).select_one("table")):
            cells = row.find_all("td")
            if len(cells) < 1 + len(DOC_SEQN):
                continue
            sale_start, sale_end = parse_period(clean(cells[0]))
            version = ProductVersion(
                company_code=self.code,
                company_name=self.name,
                storage_name=self.company.storage_name,
                product_name_raw=name,
                product_category=kind,
                sale_status="판매중지" if sale_end else status,
                sale_start_date=sale_start,
                sale_end_date=sale_end,
                source_page_url=PAGE_URL,
            )
            if sale_start:
                version.version_key = f"{sale_start:%Y%m%d}_판매개시"
            for offset, (seqn, label) in enumerate(DOC_SEQN, start=1):
                if offset >= len(cells):
                    continue
                m = _FILE_RE.search(str(cells[offset]))
                if not m:
                    continue
                file_id, found_seqn = m.group(1), m.group(2)
                version.source_product_id = version.source_product_id or file_id
                doc = self.make_document(
                    label=label,
                    url=f"{VIEWER_URL}?apdFlid={file_id}&fileSeqn={found_seqn or seqn}",
                    filename="",
                )
                if doc is not None:
                    version.documents.append(doc)
            out.append(version)
        return out

    # ------------------------------------------------------------------
    def collect_documents(self, product_version: ProductVersion) -> list[Document]:
        return product_version.documents
