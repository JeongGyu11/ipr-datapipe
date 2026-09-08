"""KDB생명 Adapter.

수집 방식: JSON_API (docs/sites/KDB_LIFE.md)
  - 목록: POST /ajax.do?scrId={화면}&isJson=1
          body = `paramJson=<이중 URL 인코딩된 JSON>`
          화면: HDLMA002M02P 판매상품 / HDLMA002M03P 판매중지상품
          categoryGroup: 2 FC/GA · 9 KDB다이렉트 · 3 방카슈랑스 · 4 단체 · 8 퇴직연금
  - 응답(JSON, EUC-KR): resultList
          GP='A' 상품 머리행 / GP='B' 판매기간 행(판매중지 화면은 GP 없음)
          PRODUCT_SUMMARY = **사업방법서** 경로, PRODUCT_GUIDE = **상품요약서** 경로
          AGREEMENT       = 약관. PDF 직접 경로이거나 `...html^720^540^1` 팝업
  - 문서: 위 경로를 그대로 GET. 약관 팝업이면 팝업 HTML 안의 PDF 링크를 모두 수집
"""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import quote

from crawler.adapters.common import absolute, decode_body, soup
from crawler.base_adapter import BaseInsurerAdapter
from models.document import Document
from models.product_version import ProductVersion
from utils.date_utils import parse_date

BASE = "https://www.kdblife.com"
PAGE_URL = f"{BASE}/ajax.do?pcmode=1&scrId=HDLMA002M02P"

SCREENS = [("HDLMA002M02P", "판매중"), ("HDLMA002M03P", "판매중지")]
CATEGORY_GROUPS = [("2", "FC/GA보험"), ("9", "KDB다이렉트보험"),
                   ("3", "방카슈랑스보험"), ("4", "단체보험"), ("8", "퇴직연금")]

#: 응답 필드 -> 화면 표시명 (필드명이 실제 의미와 다르므로 주의)
DOC_FIELDS = [("AGREEMENT", "약관"), ("PRODUCT_SUMMARY", "사업방법서"), ("PRODUCT_GUIDE", "상품요약서")]


class KDBLifeAdapter(BaseInsurerAdapter):
    code = "KDB_LIFE"
    collection_method = "JSON_API - ajax.do 판매/판매중지 × 카테고리 그룹 조회"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        versions: list[ProductVersion] = []
        seen: set[tuple] = set()
        for screen, status in SCREENS:
            for group, group_name in CATEGORY_GROUPS:
                for version in self._collect(screen, status, group, group_name):
                    key = (version.product_name_raw, version.sale_start_date,
                           version.sale_end_date, version.product_category)
                    if key in seen:
                        continue
                    seen.add(key)
                    versions.append(version)
        self.log.info("[KDB_LIFE] 상품 버전 %d건 수집", len(versions))
        self.stats["api_rows"] = len(versions)
        return versions

    # ------------------------------------------------------------------
    def _collect(self, screen: str, status: str, group: str, group_name: str) -> list[ProductVersion]:
        inner = json.dumps(
            {"pcmode": "1", "scrId": screen,
             "reqInfo": {"category": None, "searchVal": "", "categoryGroup": group,
                         "selectCategoryName": ""}},
            ensure_ascii=False,
        )
        body = "paramJson=" + quote(quote(inner, safe=""), safe="")
        response = self.client.post(
            f"{BASE}/ajax.do?scrId={screen}&isJson=1",
            content=body,
            headers={"Referer": f"{BASE}/ajax.do?pcmode=1&scrId={screen}",
                     "X-Requested-With": "XMLHttpRequest",
                     "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        )
        if response.status_code != 200:
            self.log.warning("[KDB_LIFE] %s/%s 실패 HTTP %d", screen, group_name, response.status_code)
            return []
        try:
            data = json.loads(decode_body(response, "euc-kr").strip())
        except ValueError:
            self.log.warning("[KDB_LIFE] %s/%s JSON 해석 실패", screen, group_name)
            return []

        rows = data.get("resultList") or []
        out: list[ProductVersion] = []
        product_name = ""
        category = group_name
        for row in rows:
            if row.get("GP") == "A":
                product_name = str(row.get("PRODUCT_NAME") or "").strip()
                category = str(row.get("CATEGORY_DEPTH") or group_name)
                continue
            name = str(row.get("PRODUCT_NAME") or "").strip() or product_name
            if not name:
                continue
            version = self._to_version(row, name, category, group_name, status, screen)
            if version is None:
                continue
            # 판매중지 목록은 상품명과 PRODUCT_IDX만 반환한다. 팝업 화면이 호출하는
            # 상세 JSON API에서 판매기간별 문서 행을 조회해 실제 버전으로 확장한다.
            if version.sale_start_date is None and not version.documents \
                    and not version.extra.get("agreementPopups"):
                if status == "판매중지":
                    out.extend(self._collect_sold_out_details(row, category, group_name, status))
                else:
                    self.stats["detail_missing"] = int(self.stats.get("detail_missing", 0)) + 1
                continue
            out.append(version)
        self.log.info("[KDB_LIFE] %s / %s -> %d건", status, group_name, len(out))
        return out

    def _collect_sold_out_details(
        self,
        list_row: dict,
        category: str,
        group_name: str,
        status: str,
    ) -> list[ProductVersion]:
        """판매중지 상품 팝업의 판매기간별 문서 행을 수집한다."""
        product_idx = str(list_row.get("PRODUCT_IDX") or "").strip()
        category_group = str(list_row.get("P_CATEGORY_GROUP") or "").strip()
        if not product_idx or not category_group:
            self.stats["stop_sale_detail_missing"] = int(
                self.stats.get("stop_sale_detail_missing", 0)
            ) + 1
            return []

        screen = "HDLMA002P01P"
        inner = json.dumps(
            {
                "pcmode": "1",
                "scrId": screen,
                "reqInfo": {
                    "categoryGroup": category_group,
                    "productIdx": product_idx,
                },
            },
            ensure_ascii=False,
        )
        response = self.client.post(
            f"{BASE}/ajax.do?scrId={screen}&isJson=1",
            content="paramJson=" + quote(quote(inner, safe=""), safe=""),
            headers={
                "Referer": (
                    f"{BASE}/ajax.do?pcmode=1&scrId={screen}"
                    f"&categoryGroup={category_group}&productIdx={product_idx}"
                ),
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
        )
        if response.status_code != 200:
            self.log.warning(
                "[KDB_LIFE] 판매중지 상세 실패 productIdx=%s HTTP %d",
                product_idx,
                response.status_code,
            )
            self.stats["stop_sale_detail_failed"] = int(
                self.stats.get("stop_sale_detail_failed", 0)
            ) + 1
            return []
        try:
            rows = json.loads(decode_body(response, "euc-kr").strip()).get("resultList") or []
        except (AttributeError, ValueError):
            self.log.warning("[KDB_LIFE] 판매중지 상세 JSON 해석 실패 productIdx=%s", product_idx)
            self.stats["stop_sale_detail_failed"] = int(
                self.stats.get("stop_sale_detail_failed", 0)
            ) + 1
            return []

        versions: list[ProductVersion] = []
        for raw in rows:
            row = dict(raw)
            row.setdefault("PRODUCT_IDX", product_idx)
            row.setdefault("P_CATEGORY_GROUP", category_group)
            row.setdefault("CATEGORY_NAME", list_row.get("P_CATEGORY_NAME") or category)
            name = str(row.get("PRODUCT_NAME") or list_row.get("PRODUCT_NAME") or "").strip()
            version = self._to_version(row, name, category, group_name, status, screen)
            if version is not None and (
                version.sale_start_date is not None
                or version.documents
                or version.extra.get("agreementPopups")
            ):
                versions.append(version)

        if not versions:
            self.stats["stop_sale_detail_missing"] = int(
                self.stats.get("stop_sale_detail_missing", 0)
            ) + 1
        else:
            self.stats["stop_sale_detail_versions"] = int(
                self.stats.get("stop_sale_detail_versions", 0)
            ) + len(versions)
        return versions

    def _to_version(self, row, name, category, group_name, status, screen) -> ProductVersion | None:
        sale_start = parse_date(row.get("SALE_START_DATE"))
        sale_end = parse_date(row.get("SALE_END_DATE"))
        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=name,
            product_category=" / ".join(
                x for x in (group_name, str(row.get("CATEGORY_NAME") or category or "")) if x
            ),
            source_product_id=str(row.get("PRODUCT_IDX") or ""),
            sale_status="판매중지" if sale_end else status,
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=f"{BASE}/ajax.do?pcmode=1&scrId={screen}",
            extra={"pHistoryIdx": row.get("P_HISTORY_IDX")},
        )
        if sale_start:
            version.version_key = f"{sale_start:%Y%m%d}_판매개시"

        for field, label in DOC_FIELDS:
            raw = str(row.get(field) or "").strip()
            if not raw:
                continue
            path = raw.split("^", 1)[0]           # 팝업은 `경로^가로^세로^n` 형태
            if path.lower().endswith(".html"):
                version.extra.setdefault("agreementPopups", []).append(path)
                continue
            url = absolute(BASE, path)
            if not url:
                continue
            doc = self.make_document(label=label, url=url, filename=path.rsplit("/", 1)[-1])
            if doc is not None:
                version.documents.append(doc)
        return version

    # ------------------------------------------------------------------
    def collect_documents(self, product_version: ProductVersion) -> list[Document]:
        """약관이 팝업 HTML 인 경우 팝업을 열어 주계약·특약 약관 PDF 를 모두 수집한다."""
        popups = product_version.extra.get("agreementPopups") or []
        for popup in popups:
            try:
                response = self.client.get(absolute(BASE, popup))
            except Exception as exc:  # noqa: BLE001
                self.log.warning("[KDB_LIFE] 약관 팝업 실패(%s): %s", product_version.product_name_raw, exc)
                continue
            if response.status_code != 200:
                continue
            for link in soup(decode_body(response, "euc-kr")).select("a[href]"):
                href = link["href"]
                if not href.lower().endswith(".pdf"):
                    continue
                doc = self.make_document(
                    label="약관",
                    url=absolute(BASE, href),
                    filename=href.rsplit("/", 1)[-1],
                )
                if doc is not None:
                    product_version.documents.append(doc)
        product_version.extra["agreementPopups"] = []
        return product_version.documents
