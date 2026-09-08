"""하나생명 Adapter.

수집 방식: FORM_POST (docs/sites/HANA_LIFE.md)
  - 목록: POST /anm/product/allProduct.do
          {status=on|off, object(대상), gubun(분류), pageIndex, ...}
          한 페이지 40행, 이동은 fn_search(pageIndex) → frm.submit()
  - 문서: 상품요약서/사업방법서 → GET /home/download2.do?fileName=&downFileName=
          보험약관 → GET /anm/product/download.do?code=&seq=
"""

from __future__ import annotations

from datetime import date
from urllib.parse import unquote

from crawler.adapters.common import absolute, clean, parse_period, soup, table_rows
from crawler.base_adapter import BaseInsurerAdapter
from models.product_version import ProductVersion

BASE = "https://www.hanalife.co.kr"
LIST_URL = f"{BASE}/anm/product/allProduct.do"

#: 표 열 순서(대상/분류/상품명/판매기간 다음) -> 화면 표시명
DOC_COLUMNS = ["상품요약서", "사업방법서", "보험약관"]
MODES = [("on", "판매중"), ("off", "판매중지")]
MAX_PAGES = 200


class HanaLifeAdapter(BaseInsurerAdapter):
    code = "HANA_LIFE"
    collection_method = "FORM_POST - allProduct.do status=on/off 페이지네이션 순회"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        versions: list[ProductVersion] = []
        for status_param, status in MODES:
            versions.extend(self._collect(status_param, status))
        self.log.info("[HANA_LIFE] 상품 버전 %d건 수집", len(versions))
        self.stats["html_rows"] = len(versions)
        return versions

    # ------------------------------------------------------------------
    def _collect(self, status_param: str, status: str) -> list[ProductVersion]:
        """status 별 전체 목록.

        실측 결과 이 화면은 pageIndex 와 무관하게 해당 status 의 **전체 행**을 한 번에
        내려줍니다(판매중 40행 / 판매중지 1,454행). 따라서 1회만 호출합니다.
        """
        response = self.client.post(
            LIST_URL,
            data={
                "status": status_param,
                "object": "",
                "gubun": "",
                "yyyy": "",
                "mm": "",
                "dd": "",
                "pageIndex": "1",
            },
            headers={"Referer": f"{LIST_URL}?status={status_param}"},
        )
        if response.status_code != 200:
            self.log.warning("[HANA_LIFE] status=%s 실패 HTTP %d", status_param, response.status_code)
            return []
        table = soup(response.text).select_one("table")
        rows = table_rows(table) if table is not None else []
        out = [self._to_version(row, status_param, status) for row in rows]
        out = [v for v in out if v is not None]
        self.log.info("[HANA_LIFE] status=%s -> %d건 (표 %d행)", status_param, len(out), len(rows))
        return out

    def _to_version(self, row, status_param: str, status: str) -> ProductVersion | None:
        cells = row.find_all("td")
        if len(cells) < 4 + len(DOC_COLUMNS):
            return None
        target, category, name = clean(cells[0]), clean(cells[1]), clean(cells[2])
        if not name:
            return None
        sale_start, sale_end = parse_period(clean(cells[3]))

        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=name,
            product_category=" / ".join(x for x in (target, category) if x),
            sale_status="판매중지" if sale_end else status,
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=f"{LIST_URL}?status={status_param}",
            extra={"target": target},
        )
        if sale_start:
            version.version_key = f"{sale_start:%Y%m%d}_판매개시"

        for offset, label in enumerate(DOC_COLUMNS, start=4):
            if offset >= len(cells):
                continue
            link = cells[offset].find("a", href=True)
            if link is None:
                continue
            url = absolute(BASE, link["href"])
            if not url:
                continue
            if "code=" in url and not version.source_product_id:
                version.source_product_id = url.split("code=", 1)[1].split("&")[0]
            # download2.do 는 Content-Disposition 이 EUC-KR 원문이라 깨져 보이므로
            # URL 의 downFileName 파라미터를 원본 파일명으로 사용한다.
            filename = ""
            if "downFileName=" in url:
                filename = unquote(url.split("downFileName=", 1)[1].split("&")[0])
            doc = self.make_document(label=label, url=url, filename=filename)
            if doc is not None:
                version.documents.append(doc)
        return version
