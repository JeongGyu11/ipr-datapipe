"""ABL생명 Adapter.

수집 방식: STATIC_HTML (docs/sites/ABL_LIFE.md)
  - config URL 은 공시실 허브 화면이며, 실제 목록 화면은
      판매상품     /st/pban/prdtPban/whlPrdt/whlPrdt1/whlPrdt1{1..8}?page=index
      판매중지상품 /st/pban/prdtPban/whlPrdt/whlPrdt2/whlPrdt2{1..8}?page=index
    입니다(resolved_disclosure_url).
  - 목록 행: ``li.fss_box > a[href*="whlPrdt?page="]``
  - 상세: GET /st/pban/prdtPban/whlPrdt?page={id}
          → 표(판매기간 / 사업방법서 / 상품요약서 / 약관)
  - 문서: 표 안의 정적 PDF 링크(`/cms/pban/prdtPban/whlPrdt/__icsFiles/...`)
"""

from __future__ import annotations

from datetime import date

from crawler.adapters.common import absolute, clean, parse_period, soup, table_rows
from crawler.base_adapter import BaseInsurerAdapter
from models.product_version import ProductVersion

BASE = "https://abllife.co.kr"
LIST_FMT = BASE + "/st/pban/prdtPban/whlPrdt/whlPrdt{mode}/whlPrdt{mode}{cat}?page=index"

#: 화면 탭 순서와 동일한 카테고리(끝자리)
CATEGORIES = [
    ("1", "종신"), ("2", "변액"), ("3", "연금"), ("4", "보장"),
    ("5", "저축"), ("6", "단체보험"), ("7", "방카슈랑스"), ("8", "제도성특약"),
]
MODES = [("1", "판매중"), ("2", "판매중지")]

#: 상세 표의 열 순서 -> 화면 표시명
DOC_COLUMNS = ["사업방법서", "상품요약서", "약관"]


class ABLLifeAdapter(BaseInsurerAdapter):
    code = "ABL_LIFE"
    collection_method = "STATIC_HTML - 판매/판매중지 × 카테고리 8종 목록 + 상품 상세 표"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        products = []
        for mode, status in MODES:
            for cat, cat_name in CATEGORIES:
                products.extend(self._collect_products(mode, status, cat, cat_name))
        self.log.info("[ABL_LIFE] 상품 %d건 수집, 상세 조회 시작", len(products))
        self.stats["products"] = len(products)

        limit = self.runtime_options.get("max_products")
        if limit and len(products) > int(limit):
            self.stats["coverage_capped"] = True
            self.stats["products_total"] = len(products)
            self.stats["products_skipped"] = len(products) - int(limit)
            products = products[: int(limit)]

        versions: list[ProductVersion] = []
        for index, item in enumerate(products, start=1):
            versions.extend(self._collect_versions(item))
            if index % 50 == 0:
                self.log.info("[ABL_LIFE] 상세 진행 %d/%d", index, len(products))
        self.log.info("[ABL_LIFE] 상품 버전 %d건 수집", len(versions))
        return versions

    # ------------------------------------------------------------------
    def _collect_products(self, mode, status, cat, cat_name) -> list[dict]:
        url = LIST_FMT.format(mode=mode, cat=cat)
        response = self.client.get(url)
        if response.status_code != 200:
            self.log.warning("[ABL_LIFE] %s/%s 실패 HTTP %d", status, cat_name, response.status_code)
            return []
        out = []
        for link in soup(response.text).select('li.fss_box a[href*="whlPrdt?page="]'):
            name = clean(link.select_one("span.subject") or link)
            detail = absolute(BASE, link["href"])
            if name and detail:
                out.append({"name": name, "url": detail, "status": status,
                            "category": cat_name, "listUrl": url})
        self.log.info("[ABL_LIFE] %s / %s -> 상품 %d건", status, cat_name, len(out))
        return out

    def _collect_versions(self, item: dict) -> list[ProductVersion]:
        try:
            response = self.client.get(item["url"])
        except Exception as exc:  # noqa: BLE001 - 상품 1건 실패가 전체를 막지 않도록
            self.log.warning("[ABL_LIFE] 상세 실패(%s): %s", item["name"], exc)
            return []
        if response.status_code != 200:
            return []
        table = soup(response.text).select_one("table")
        if table is None:
            return []

        out: list[ProductVersion] = []
        for row in table_rows(table):
            cells = row.find_all("td")
            if len(cells) < 1 + len(DOC_COLUMNS):
                continue
            sale_start, sale_end = parse_period(clean(cells[0]))
            version = ProductVersion(
                company_code=self.code,
                company_name=self.name,
                storage_name=self.company.storage_name,
                product_name_raw=item["name"],
                product_category=item["category"],
                source_product_id=item["url"].split("page=", 1)[-1],
                sale_status="판매중지" if sale_end else item["status"],
                sale_start_date=sale_start,
                sale_end_date=sale_end,
                source_page_url=item["listUrl"],
            )
            if sale_start:
                version.version_key = f"{sale_start:%Y%m%d}_판매개시"
            for offset, label in enumerate(DOC_COLUMNS, start=1):
                if offset >= len(cells):
                    continue
                link = cells[offset].find("a", href=True)
                if link is None:
                    continue
                url = absolute(BASE, link["href"])
                if not url:
                    continue
                doc = self.make_document(label=label, url=url,
                                         filename=url.rsplit("/", 1)[-1])
                if doc is not None:
                    version.documents.append(doc)
            out.append(version)
        return out
