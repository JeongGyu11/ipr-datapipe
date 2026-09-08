"""라이나손해보험(처브) Adapter.

수집 방식: STATIC_HTML (docs/sites/LINA_NON_LIFE.md)
  - config URL(chubb.com/.../product-disclosure.html)은 공시 안내 화면입니다.
    실제 상품 목록은 **별도 도메인**의 아래 화면입니다(resolved_disclosure_url).
      판매중     https://ec.aceinsurance.co.kr/jsp/acelimited/notice/productNoticeV2.jsp?status=Y
      판매중지   같은 URL의 status=N
  - 목록: 카테고리별 표 여러 개. 열 = 상품명 / 판매기간 / 사업방법서 / 상품약관 / 상품요약서
  - 문서: GET /jsp/file/WebProductFiledown.jsp?fileType=1|2|3&fileName=...
          (1=사업방법서, 2=약관, 3=상품요약서)
"""

from __future__ import annotations

from datetime import date

from crawler.adapters.common import absolute, clean, parse_period, soup, table_rows
from crawler.base_adapter import BaseInsurerAdapter
from models.product_version import ProductVersion

BASE = "https://ec.aceinsurance.co.kr"
LIST_URL = BASE + "/jsp/acelimited/notice/productNoticeV2.jsp"
REFERER = "https://www.chubb.com/kr-kr/disclosure/product.html"

MODES = [("Y", "판매중"), ("N", "판매중지")]

#: 표 열 순서(상품명/판매기간 다음) -> 화면 표시명
DOC_COLUMNS = ["사업방법서", "상품약관", "상품요약서"]


class LinaNonLifeAdapter(BaseInsurerAdapter):
    code = "LINA_NON_LIFE"
    collection_method = "STATIC_HTML - productNoticeV2.jsp status=Y/N 전량 파싱"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        versions: list[ProductVersion] = []
        for status_param, status in MODES:
            versions.extend(self._collect(status_param, status))
        self.log.info("[LINA_NON_LIFE] 상품 버전 %d건 수집", len(versions))
        self.stats["html_rows"] = len(versions)
        return versions

    # ------------------------------------------------------------------
    def _collect(self, status_param: str, status: str) -> list[ProductVersion]:
        response = self.client.get(
            LIST_URL, params={"status": status_param},
            headers={"Referer": REFERER}, timeout=max(self.config.timeout, 120),
        )
        if response.status_code != 200:
            self.log.warning("[LINA_NON_LIFE] status=%s 실패 HTTP %d", status_param, response.status_code)
            return []
        document = soup(response.text)

        out: list[ProductVersion] = []
        product_name = ""
        for table in document.select("table"):
            headers = [clean(th) for th in table.select("th")]
            if "상품명" not in headers:
                continue
            category = self._category_of(table)
            for row in table_rows(table):
                cells = row.find_all("td")
                if not cells:
                    continue
                # 상품명 칸은 rowspan 으로 첫 행에만 나온다.
                if len(cells) >= 2 + len(DOC_COLUMNS):
                    product_name = clean(cells[0]) or product_name
                    cells = cells[1:]
                if len(cells) < 1 + len(DOC_COLUMNS) or not product_name:
                    continue
                sale_start, sale_end = parse_period(clean(cells[0]))
                version = ProductVersion(
                    company_code=self.code,
                    company_name=self.name,
                    storage_name=self.company.storage_name,
                    product_name_raw=product_name,
                    product_category=category,
                    sale_status="판매중지" if sale_end else status,
                    sale_start_date=sale_start,
                    sale_end_date=sale_end,
                    source_page_url=f"{LIST_URL}?status={status_param}",
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
                    doc = self.make_document(label=label, url=url, filename="")
                    if doc is not None:
                        version.documents.append(doc)
                out.append(version)
        self.log.info("[LINA_NON_LIFE] status=%s -> %d건", status_param, len(out))
        return out

    @staticmethod
    def _category_of(table) -> str:
        """표 바로 앞의 제목 텍스트를 카테고리로 사용한다."""
        node = table
        for _ in range(6):
            node = node.find_previous(["h2", "h3", "h4", "strong", "caption"])
            if node is None:
                break
            text = clean(node)
            if text:
                return text
        return ""
