"""한화생명 Adapter.

수집 방식: JSON_API 3단계 (docs/sites/HANWHA_LIFE.md)
  - config URL 의 옛 ASP 경로는 폐기되어 홈으로 리다이렉트됩니다.
    실제 화면(resolved_disclosure_url)
      판매상품     /main/disclosure/goods/disclosurenotice/DF_GDDN000_P10000.do?MENU_ID1=DF_GDGL000&MENU_ID2=DF_GDGL000_P10000
      판매중지상품 위 URL 의 MENU_ID2=DF_GDGL000_P20000 (목록 API 는 sellFlag 로 구분)
  - 목록 API: POST /main/disclosure/goods/goodslist/getList.do
      PType=1                          → list1: 분류(SELL_TYPE, GOODS_TYPE)
      PType=2 + sellType/goodsType     → list2: 상품(IDX, GOODS_NAME)
      PType=3 + goodsIndex=IDX         → list3: 판매기간 + 파일명
          SELL_START_DT / SELL_END_DT
          FILE_NAME1 상품요약서 / FILE_NAME2 사업방법서 / FILE_NAME3~ 약관
  - 문서: POST https://file.hanwhalife.com/www/announce/goods/download_chk.asp
      body `file_name=<EUC-KR URL 인코딩된 파일명>`  (**본 사이트 도메인이 아님**)

주의: 구형 TLS 스택이라 `options.legacy_ssl: true` 가 필요합니다.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote

from crawler.base_adapter import BaseInsurerAdapter, FetchResult
from crawler.http_client import AccessDeniedError
from models.document import Document, DownloadStatus
from models.product_version import ProductVersion
from utils.date_utils import parse_date
from utils.file_utils import filename_from_content_disposition

BASE = "https://www.hanwhalife.com"
PAGE_URL = (BASE + "/main/disclosure/goods/disclosurenotice/DF_GDDN000_P10000.do"
                   "?MENU_ID1=DF_GDGL000&MENU_ID2=DF_GDGL000_P10000")
LIST_URL = BASE + "/main/disclosure/goods/goodslist/getList.do"
DOWNLOAD_URL = "https://file.hanwhalife.com/www/announce/goods/download_chk.asp"

MENU_ID = "DF_GDGL000"
MODES = [("Y", "판매중"), ("N", "판매중지")]

#: list3 필드 -> 화면 표시명 (표 머리글: 판매기간 / 상품요약서 / 사업방법서 / 약관)
DOC_FIELDS = [("FILE_NAME1", "상품요약서"), ("FILE_NAME2", "사업방법서")]
#: 약관은 FILE_NAME3 부터 여러 개(_1, _2 …)로 제공될 수 있다.
POLICY_FIELD_RE = re.compile(r"^FILE_NAME([3-9]|\d{2,})$")


class HanwhaLifeAdapter(BaseInsurerAdapter):
    code = "HANWHA_LIFE"
    legacy_ssl = True
    collection_method = "JSON_API - goodslist/getList.do PType 1→2→3 순회"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        self.client.get(PAGE_URL)          # 세션 확보
        products: list[tuple] = []
        for sell_flag, status in MODES:
            for category in self._call(1, sell_flag).get("list1") or []:
                sell_type = str(category.get("SELL_TYPE") or "")
                goods_type = str(category.get("GOODS_TYPE") or "")
                cat_name = " / ".join(
                    x for x in (str(category.get("SELL_TYPE_NM") or ""),
                                str(category.get("GOODS_TYPE_NM") or "")) if x
                )
                rows = self._call(2, sell_flag, sell_type, goods_type).get("list2") or []
                self.log.info("[HANWHA_LIFE] %s / %s -> 상품 %d건", status, cat_name, len(rows))
                for row in rows:
                    products.append((sell_flag, status, sell_type, goods_type, cat_name,
                                     row.get("IDX"), str(row.get("GOODS_NAME") or "")))

        self.stats["products"] = len(products)
        limit = self.runtime_options.get("max_products")
        if limit and len(products) > int(limit):
            self.stats["coverage_capped"] = True
            self.stats["products_total"] = len(products)
            self.stats["products_skipped"] = len(products) - int(limit)
            products = products[: int(limit)]

        versions: list[ProductVersion] = []
        for index, item in enumerate(products, start=1):
            versions.extend(self._versions(*item))
            if index % 50 == 0:
                self.log.info("[HANWHA_LIFE] 상세 진행 %d/%d", index, len(products))
        self.log.info("[HANWHA_LIFE] 상품 버전 %d건 수집", len(versions))
        return versions

    # ------------------------------------------------------------------
    def _call(self, ptype: int, sell_flag: str, sell_type: str = "",
              goods_type: str = "", goods_index: str = "") -> dict:
        response = self.client.post(
            LIST_URL,
            data={"PType": str(ptype), "sellFlag": sell_flag, "goodsType": goods_type,
                  "sellType": sell_type, "goodsIndex": goods_index, "schText": "",
                  "__MENU_ID": MENU_ID},
            headers={"Referer": PAGE_URL, "X-Requested-With": "XMLHttpRequest",
                     "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                     "Accept": "application/json, text/javascript, */*; q=0.01"},
        )
        if response.status_code != 200:
            self.log.warning("[HANWHA_LIFE] PType=%d 실패 HTTP %d", ptype, response.status_code)
            return {}
        try:
            return response.json() or {}
        except ValueError:
            self.log.warning("[HANWHA_LIFE] PType=%d JSON 해석 실패", ptype)
            return {}

    def _versions(self, sell_flag, status, sell_type, goods_type,
                  cat_name, idx, goods_name) -> list[ProductVersion]:
        if idx is None:
            return []
        rows = self._call(3, sell_flag, sell_type, goods_type, str(idx)).get("list3") or []
        out: list[ProductVersion] = []
        for row in rows:
            sale_start = parse_date(str(row.get("SELL_START_DT") or "").strip())
            sale_end = parse_date(str(row.get("SELL_END_DT") or "").strip())
            version = ProductVersion(
                company_code=self.code,
                company_name=self.name,
                storage_name=self.company.storage_name,
                product_name_raw=str(row.get("GOODS_NAME") or goods_name).strip(),
                product_category=cat_name,
                source_product_id=str(idx),
                sale_status="판매중지" if sale_end else status,
                sale_start_date=sale_start,
                sale_end_date=sale_end,
                source_page_url=PAGE_URL,
            )
            if sale_start:
                version.version_key = f"{sale_start:%Y%m%d}_판매개시"

            for field, label in DOC_FIELDS:
                self._add(version, label, str(row.get(field) or "").strip())
            # 약관은 FILE_NAME3 이후 여러 개
            for field in sorted(k for k in row if POLICY_FIELD_RE.match(k)):
                self._add(version, "약관", str(row.get(field) or "").strip())
            out.append(version)
        return out

    def _add(self, version: ProductVersion, label: str, file_name: str) -> None:
        if not file_name:
            return
        doc = self.make_document(
            label=label,
            filename=file_name,
            fileName=file_name,
            source_locator=f"POST|fileName={file_name}",
        )
        if doc is not None:
            version.documents.append(doc)

    # ------------------------------------------------------------------
    def fetch_document(self, document: Document) -> FetchResult:
        file_name = document.download_hint.get("fileName")
        if not file_name:
            return FetchResult(False, DownloadStatus.NO_DOCUMENT_LINK, reason="fileName 없음")
        # 화면과 동일하게 EUC-KR 로 URL 인코딩한다(UTF-8 로 보내면 파일을 찾지 못함).
        body = "file_name=" + quote(file_name, encoding="euc-kr", errors="replace")
        try:
            response = self.client.post(
                DOWNLOAD_URL, content=body,
                headers={"Referer": PAGE_URL,
                         "Content-Type": "application/x-www-form-urlencoded"},
            )
        except AccessDeniedError as exc:
            return FetchResult(False, DownloadStatus.ACCESS_DENIED, reason=str(exc))
        except Exception as exc:  # noqa: BLE001
            return FetchResult(False, DownloadStatus.DOWNLOAD_FAILED, reason=f"{type(exc).__name__}: {exc}")

        # Content-Disposition 이 EUC-KR 원문이라 깨지므로 목록에서 받은 파일명을 우선한다.
        original = file_name or filename_from_content_disposition(
            response.headers.get("content-disposition", "")
        )
        return FetchResult(
            ok=response.status_code == 200,
            status=DownloadStatus.SUCCESS if response.status_code == 200 else DownloadStatus.INVALID_RESPONSE,
            content=response.content,
            content_type=response.headers.get("content-type", ""),
            original_filename=original,
            http_status=response.status_code,
            final_url=DOWNLOAD_URL,
        )
