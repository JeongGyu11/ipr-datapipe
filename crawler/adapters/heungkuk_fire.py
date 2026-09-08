"""흥국화재 Adapter.

수집 방식: FORM_POST (docs/sites/HEUNGKUK_FIRE.md)
  - 목록: POST /FRW/announce/insGoodsGongsiSale.do
          {mode=go|stop, type=1 장기 / 2 일반 / 3 자동차, page, searchvalue}
          페이지당 10행, goPage(page) 로 이동
  - 문서: POST /common/download.do {filePath, fileRealName, fileSaveName, mode=View}
          화면의 fn_filedownX(path, name, saveName) 인자를 그대로 사용
"""

from __future__ import annotations

from datetime import date

from crawler.adapters.common import clean, js_call_args, parse_period, soup, table_rows
from crawler.base_adapter import BaseInsurerAdapter, FetchResult
from crawler.http_client import AccessDeniedError
from models.document import Document, DownloadStatus
from models.product_version import ProductVersion
from utils.file_utils import filename_from_content_disposition

BASE = "https://www.heungkukfire.co.kr"
LIST_URL = f"{BASE}/FRW/announce/insGoodsGongsiSale.do"
DOWNLOAD_URL = f"{BASE}/common/download.do"

MODES = [("go", "판매중"), ("stop", "판매중지")]
TYPES = [("1", "장기보험"), ("2", "일반보험"), ("3", "자동차보험")]
MAX_PAGES = 400


class HeungkukFireAdapter(BaseInsurerAdapter):
    code = "HEUNGKUK_FIRE"
    collection_method = "FORM_POST - insGoodsGongsiSale.do mode×type 페이지네이션 순회"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        versions: list[ProductVersion] = []
        for mode, status in MODES:
            for ins_type, category in TYPES:
                versions.extend(self._collect(mode, status, ins_type, category))
        self.log.info("[HEUNGKUK_FIRE] 상품 버전 %d건 수집", len(versions))
        self.stats["html_rows"] = len(versions)
        return versions

    # ------------------------------------------------------------------
    def _collect(self, mode: str, status: str, ins_type: str, category: str) -> list[ProductVersion]:
        out: list[ProductVersion] = []
        seen: set[tuple] = set()
        for page in range(1, MAX_PAGES + 1):
            response = self.client.post(
                LIST_URL,
                data={"mode": mode, "type": ins_type, "page": str(page), "searchvalue": ""},
                headers={"Referer": LIST_URL},
            )
            if response.status_code != 200:
                self.log.warning("[HEUNGKUK_FIRE] %s/%s page=%d 실패 HTTP %d",
                                 mode, category, page, response.status_code)
                break
            table = soup(response.text).select_one("div.tbl_chk_tb table")
            rows = table_rows(table) if table is not None else []
            if not rows:
                break
            fresh = 0
            for row in rows:
                version = self._to_version(row, mode, status, category)
                if version is None:
                    continue
                key = (version.product_name_raw, version.sale_start_date, version.product_category)
                if key in seen:
                    continue
                seen.add(key)
                out.append(version)
                fresh += 1
            if fresh == 0:
                break
        self.log.info("[HEUNGKUK_FIRE] %s/%s -> %d건", mode, category, len(out))
        return out

    def _to_version(self, row, mode: str, status: str, category: str) -> ProductVersion | None:
        cells = row.find_all("td")
        if len(cells) < 5:
            return None
        sub_category, sale_year, name, sale_day = (clean(cells[i]) for i in range(4))
        if not name:
            return None
        # 판매 화면은 단일 판매개시일, 판매중지 화면은 '시작 ~ 종료' 형태로 표기된다(실측).
        sale_start, sale_end = parse_period(sale_day)

        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=name,
            product_category=" / ".join(x for x in (category, sub_category) if x),
            sale_status="판매중지" if sale_end else status,
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=LIST_URL,
            extra={"saleYear": sale_year, "mode": mode},
        )
        if sale_start:
            version.version_key = f"{sale_start:%Y%m%d}_판매개시"

        for link in cells[4].find_all("a"):
            args = js_call_args(link.get("onclick") or "", "fn_filedownX")
            if len(args) < 3:
                continue
            doc = self.make_document(
                label=clean(link),
                filename=args[1],
                filePath=args[0],
                fileRealName=args[1],
                fileSaveName=args[2],
                source_locator=f"POST|filePath={args[0]}|fileSaveName={args[2]}|fileRealName={args[1]}",
            )
            if doc is not None:
                version.documents.append(doc)
        return version

    # ------------------------------------------------------------------
    def fetch_document(self, document: Document) -> FetchResult:
        hint = document.download_hint
        if not hint.get("fileSaveName"):
            return FetchResult(False, DownloadStatus.NO_DOCUMENT_LINK, reason="fileSaveName 없음")
        payload = {
            "filePath": hint.get("filePath", ""),
            "fileRealName": hint.get("fileRealName", ""),
            "fileSaveName": hint["fileSaveName"],
            "mode": "View",
        }
        try:
            response = self.client.post(DOWNLOAD_URL, data=payload, headers={"Referer": LIST_URL})
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
