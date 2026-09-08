"""동양생명 Adapter.

수집 방식: FORM_POST (docs/sites/TONGYANG_LIFE.md)
  - config URL 은 공시실 진입 화면입니다. 실제 목록 화면(resolved_disclosure_url)
      판매상품     /paging/WE_AC_WEPAAP020100L
      판매중지상품 /paging/WE_AC_WEPAAP020201L
  - 페이지 이동은 화면의 PP_Query('mainform','dw_99',N) 이 만드는 폼 값을 그대로 전송
      _biz_op_code=_Q, _paging_action=PP, _paging_dw_name=dw_99, _paging_page_idx=N
  - 표: 번호 / 판매채널 / 구분 / 상품명 / 판매기간(시작) / 판매기간(종료) / 문서…
  - 문서: 링크의 MasFiledownload('_N','<FILE_GRP_ID>') 토큰을
          POST /process/CO_ComDownload {_biz_op_code=FDL, FILE_GRP_ID}
"""

from __future__ import annotations

from datetime import date

from crawler.adapters.common import clean, js_call_args, soup, table_rows
from crawler.base_adapter import BaseInsurerAdapter, FetchResult
from crawler.http_client import AccessDeniedError
from models.document import Document, DownloadStatus
from models.product_version import ProductVersion
from utils.date_utils import parse_date
from utils.file_utils import filename_from_content_disposition

BASE = "https://pbano.myangel.co.kr"
DOWNLOAD_URL = f"{BASE}/process/CO_ComDownload"

SCREENS = [("/paging/WE_AC_WEPAAP020100L", "판매중"), ("/paging/WE_AC_WEPAAP020201L", "판매중지")]
MAX_PAGES = 400


class TongyangLifeAdapter(BaseInsurerAdapter):
    code = "TONGYANG_LIFE"
    collection_method = "FORM_POST - WE_AC_WEPAAP0201/0202 페이지네이션 순회"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        versions: list[ProductVersion] = []
        for path, status in SCREENS:
            versions.extend(self._collect(path, status))
        self.log.info("[TONGYANG_LIFE] 상품 버전 %d건 수집", len(versions))
        self.stats["html_rows"] = len(versions)
        return versions

    # ------------------------------------------------------------------
    def _collect(self, path: str, status: str) -> list[ProductVersion]:
        url = BASE + path
        self.client.get(url)          # 세션/폼 초기화
        out: list[ProductVersion] = []
        seen: set[tuple] = set()
        for page in range(1, MAX_PAGES + 1):
            data = {
                "_biz_op_code": "_Q", "_biz_dw_00": "",
                "pagenum": "1", "sale_kind": "ALL", "goods_kind": "ALL", "nameStr": "",
                "_paging_action": "PP", "_paging_dw_name": "dw_99",
                "_paging_row_idx": "0", "_paging_page_idx": str(page),
                "_paging_dw_99_row_idx": "0", "_paging_dw_99_page_idx": str(page),
            }
            response = self.client.post(url, data=data, headers={"Referer": url})
            if response.status_code != 200:
                self.log.warning("[TONGYANG_LIFE] %s page=%d 실패 HTTP %d", path, page, response.status_code)
                break
            rows = table_rows(soup(response.text).select_one("table"))
            if not rows:
                break
            fresh = 0
            for row in rows:
                version = self._to_version(row, url, status)
                if version is None:
                    continue
                key = (version.product_name_raw, version.sale_start_date, version.sale_end_date)
                if key in seen:
                    continue
                seen.add(key)
                out.append(version)
                fresh += 1
            if fresh == 0:
                break
        self.log.info("[TONGYANG_LIFE] %s -> %d건", status, len(out))
        return out

    def _to_version(self, row, url: str, status: str) -> ProductVersion | None:
        cells = row.find_all("td")
        if len(cells) < 6:
            return None
        channel, kind, name = clean(cells[1]), clean(cells[2]), clean(cells[3])
        if not name:
            return None
        sale_start = parse_date(clean(cells[4]))
        sale_end = parse_date(clean(cells[5]))

        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=name,
            product_category=" / ".join(x for x in (channel, kind) if x),
            sale_status="판매중지" if sale_end else status,
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=url,
            extra={"channel": channel},
        )
        if sale_start:
            version.version_key = f"{sale_start:%Y%m%d}_판매개시"

        for cell in cells[6:]:
            for link in cell.find_all("a", href=True):
                args = js_call_args(link["href"], "MasFiledownload")
                if len(args) < 2 or not args[1]:
                    continue
                img = link.find("img")
                label = (img.get("alt") if img is not None else "") or clean(link)
                doc = self.make_document(
                    label=label,
                    filename="",
                    fileGrpId=args[1],
                    source_locator=f"POST|fileGrpId={args[1]}",
                )
                if doc is not None:
                    version.documents.append(doc)
        return version

    # ------------------------------------------------------------------
    def fetch_document(self, document: Document) -> FetchResult:
        token = document.download_hint.get("fileGrpId")
        if not token:
            return FetchResult(False, DownloadStatus.NO_DOCUMENT_LINK, reason="FILE_GRP_ID 없음")
        try:
            response = self.client.post(
                DOWNLOAD_URL,
                data={"_biz_op_code": "FDL", "FILE_GRP_ID": token,
                      "FILE_PATH": "", "FILE_NAME": "", "USER_FILE_NM": ""},
                headers={"Referer": BASE + SCREENS[0][0]},
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
