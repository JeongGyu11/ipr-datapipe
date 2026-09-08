"""iM라이프 Adapter.

수집 방식: FORM_POST (docs/sites/IM_LIFE.md)
  - 목록: POST /BA/BA_A020.do  {sellType: 1=판매중 / 0=판매중지}
          → 개인 / 단체 / 독립특약 표가 한 응답에 함께 옴
  - 문서: POST /www/downloadChk.do {fileName}
          (화면의 fileDownload() 가 만드는 폼과 동일)
"""

from __future__ import annotations

from datetime import date

from crawler.adapters.common import clean, js_call_args, soup, table_rows
from crawler.base_adapter import BaseInsurerAdapter, FetchResult
from models.document import Document, DownloadStatus
from models.product_version import ProductVersion
from utils.date_utils import parse_date
from utils.file_utils import filename_from_content_disposition
from crawler.http_client import AccessDeniedError

BASE = "https://www.imlifeins.co.kr"
LIST_URL = f"{BASE}/BA/BA_A020.do"
DOWNLOAD_URL = f"{BASE}/www/downloadChk.do"

#: 표 열 순서 (구분/상품명 제외) -> 화면 표시명
DOC_COLUMNS = ["상품요약서", "사업방법서", "보험약관"]


class IMLifeAdapter(BaseInsurerAdapter):
    code = "IM_LIFE"
    collection_method = "FORM_POST - BA_A020.do sellType 1/0 전량 조회"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        versions: list[ProductVersion] = []
        for sell_type, status in (("1", "판매중"), ("0", "판매중지")):
            versions.extend(self._collect(sell_type, status))
        self.log.info("[IM_LIFE] 상품 버전 %d건 수집", len(versions))
        self.stats["html_rows"] = len(versions)
        return versions

    # ------------------------------------------------------------------
    def _collect(self, sell_type: str, status: str) -> list[ProductVersion]:
        response = self.client.post(
            LIST_URL, data={"sellType": sell_type}, headers={"Referer": LIST_URL}
        )
        if response.status_code != 200:
            self.log.warning("[IM_LIFE] sellType=%s 조회 실패 HTTP %d", sell_type, response.status_code)
            return []

        out: list[ProductVersion] = []
        for table in soup(response.text).select("table.colTbl"):
            caption = clean(table.caption) if table.caption else ""
            category = ""
            product_name = ""
            for row in table_rows(table):
                headers = row.find_all("th")
                cells = row.find_all("td")
                if headers:
                    category = clean(headers[0])
                if cells and cells[0].get("rowspan") and len(cells) > len(DOC_COLUMNS) + 2:
                    product_name = clean(cells[0])
                    cells = cells[1:]
                elif cells and len(cells) == len(DOC_COLUMNS) + 3:
                    product_name = clean(cells[0])
                    cells = cells[1:]
                if len(cells) < len(DOC_COLUMNS) + 2 or not product_name:
                    continue
                version = self._to_version(caption, category, product_name, cells, status)
                if version is not None:
                    out.append(version)
        self.log.info("[IM_LIFE] sellType=%s -> %d건", sell_type, len(out))
        return out

    def _to_version(self, caption, category, product_name, cells, status) -> ProductVersion | None:
        sale_start = parse_date(clean(cells[0]))
        sale_end = parse_date(clean(cells[1]))
        if sale_start is None:
            return None
        channel = "단체" if "단체" in caption else ("독립특약" if "독립특약" in caption else "개인")
        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=product_name,
            product_category=" / ".join(x for x in (channel, category) if x),
            sale_status="판매중지" if sale_end else status,
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=LIST_URL,
            version_key=f"{sale_start:%Y%m%d}_판매개시",
            extra={"channel": channel},
        )
        for offset, label in enumerate(DOC_COLUMNS, start=2):
            if offset >= len(cells):
                continue
            link = cells[offset].find("a", href=True)
            if link is None:
                continue
            args = js_call_args(link["href"], "fileDownload")
            if not args or not args[0]:
                continue
            file_name = args[0]
            doc = self.make_document(
                label=label,
                filename=file_name.rsplit("/", 1)[-1],
                fileName=file_name,
                source_locator=f"POST|fileName={file_name}",
            )
            if doc is not None:
                version.documents.append(doc)
        return version

    # ------------------------------------------------------------------
    def fetch_document(self, document: Document) -> FetchResult:
        """iM라이프는 URL 이 아니라 폼 POST 로 파일을 받는다."""
        file_name = document.download_hint.get("fileName")
        if not file_name:
            return FetchResult(False, DownloadStatus.NO_DOCUMENT_LINK, reason="fileName 없음")
        try:
            response = self.client.post(
                DOWNLOAD_URL, data={"fileName": file_name}, headers={"Referer": LIST_URL}
            )
        except AccessDeniedError as exc:
            return FetchResult(False, DownloadStatus.ACCESS_DENIED, reason=str(exc))
        except Exception as exc:  # noqa: BLE001
            return FetchResult(False, DownloadStatus.DOWNLOAD_FAILED, reason=f"{type(exc).__name__}: {exc}")

        original = (
            filename_from_content_disposition(response.headers.get("content-disposition", ""))
            or document.original_filename
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
