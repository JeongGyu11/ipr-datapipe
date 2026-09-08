"""메트라이프생명 Adapter.

수집 방식: STATIC_HTML (docs/sites/METLIFE.md)
  - 목록: GET /pn/mcvrgProd/retrieveMcvrgProdMain.do
          → 주보험 상품 + 모든 이전 판매기간이 한 페이지에 전부 렌더링됨(실측 747행)
  - 특약: POST /pn/mcvrgProd/retrieveMcvrgProdPop.do {insProdSeq, seq}
          → 해당 판매기간의 특약 약관 목록
  - 문서: GET /pn/mcvrgProd/mcvrgProdDownloadFile.do?insProdSeq=&seq=&fnum=
          fnum 01=사업방법서 / 02=상품요약서 / 03=약관 (표 열 순서로 확인)
"""

from __future__ import annotations

import re
from datetime import date

from crawler.adapters.common import absolute, clean, parse_period, soup, table_rows
from crawler.base_adapter import BaseInsurerAdapter
from models.document import Document
from models.product_version import ProductVersion

BASE = "https://brand.metlife.co.kr"
LIST_URL = f"{BASE}/pn/mcvrgProd/retrieveMcvrgProdMain.do"
POPUP_URL = f"{BASE}/pn/mcvrgProd/retrieveMcvrgProdPop.do"

#: 판매기간 행의 td 인덱스 -> 화면 표시명 (표 머리글 순서와 동일)
DOC_COLUMNS = {1: "사업방법서", 2: "상품요약서", 3: "약관"}


class MetLifeAdapter(BaseInsurerAdapter):
    code = "METLIFE"
    collection_method = "STATIC_HTML - 공시 화면 HTML 전량 파싱 + 특약 팝업 조회"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        response = self.client.get(LIST_URL)
        if response.status_code != 200:
            self.log.warning("[METLIFE] 목록 조회 실패 HTTP %d", response.status_code)
            return []
        document = soup(response.text)
        table = document.select_one("table.tblList")
        if table is None:
            self.log.warning("[METLIFE] 상품 표를 찾지 못했습니다.")
            return []

        versions: list[ProductVersion] = []
        category = ""
        product_name = ""
        for row in table_rows(table):
            header = row.find("th", class_="bgW")
            if header is not None:
                category = clean(header)
            cells = row.find_all("td", recursive=False)
            if not cells:
                continue
            # 상품 머리 행: [상품명(rowspan), '이전 판매기간 펼치기'(colspan=7)]
            if len(cells) == 2 and cells[1].find("button") is not None:
                product_name = clean(cells[0])
                continue
            if len(cells) == 1 and cells[0].find("button") is not None:
                continue
            # 이전 판매기간 행은 상품명을 매 행 반복한다(td 8개).
            if len(cells) >= len(DOC_COLUMNS) + 5:
                product_name = clean(cells[0]) or product_name
                cells = cells[1:]
            version = self._to_version(category, product_name, cells)
            if version is not None:
                versions.append(version)

        self.log.info("[METLIFE] 상품 버전 %d건 수집", len(versions))
        self.stats["html_rows"] = len(versions)
        return versions

    # ------------------------------------------------------------------
    def _to_version(self, category: str, product_name: str, cells) -> ProductVersion | None:
        if not product_name or not cells:
            return None
        sale_start, sale_end = parse_period(clean(cells[0]))
        if sale_start is None:
            return None

        ins_prod_seq, seq = "", ""
        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=product_name,
            product_category=category,
            sale_status="판매중" if sale_end is None else "판매중지",
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=LIST_URL,
            version_key=f"{sale_start:%Y%m%d}_판매개시",
        )

        for index, label in DOC_COLUMNS.items():
            if index >= len(cells):
                continue
            link = cells[index].find("a", href=True)
            if link is None:
                continue
            url = absolute(BASE, link["href"])
            ins_prod_seq = _param(url, "insProdSeq") or ins_prod_seq
            seq = _param(url, "seq") or seq
            doc = self.make_document(label=label, url=url, filename=clean(link))
            if doc is not None:
                version.documents.append(doc)

        version.source_product_id = ins_prod_seq
        version.extra = {"insProdSeq": ins_prod_seq, "seq": seq}
        return version

    # ------------------------------------------------------------------
    def collect_documents(self, product_version: ProductVersion) -> list[Document]:
        """주보험 문서 + 해당 판매기간의 특약 약관을 모두 돌려준다."""
        documents = list(product_version.documents)
        ins_prod_seq = product_version.extra.get("insProdSeq")
        seq = product_version.extra.get("seq")
        if not (ins_prod_seq and seq):
            return documents
        try:
            response = self.client.post(
                POPUP_URL,
                data={"insProdSeq": ins_prod_seq, "seq": seq},
                headers={"Referer": LIST_URL},
            )
        except Exception as exc:  # noqa: BLE001 - 특약 조회 실패가 주계약 수집을 막지 않도록
            self.log.warning("[METLIFE] 특약 조회 실패(%s): %s", product_version.product_name_raw, exc)
            return documents
        if response.status_code != 200:
            return documents

        for row in table_rows(soup(response.text).select_one("table.tblNoti")):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            rider_name = clean(cells[0])
            link = cells[2].find("a", href=True)
            if link is None or not rider_name:
                continue
            doc = self.make_document(
                label=f"특약 약관 - {rider_name}",
                url=absolute(BASE, link["href"]),
                filename="",
            )
            if doc is not None:
                documents.append(doc)
        product_version.documents = documents
        return documents


def _param(url: str, name: str) -> str:
    m = re.search(rf"[?&]{name}=([^&]+)", url or "")
    return m.group(1) if m else ""
