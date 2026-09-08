"""IBK연금보험 Adapter.

수집 방식: STATIC_HTML (docs/sites/IBK_LIFE.md)
  - 목록(EUC-KR 정적 HTML, 페이지네이션 없음)
      /process/HP_PBANO_PDT_SP_INDV   판매상품 · 개인연금
      /process/HP_PBANO_PDT_SP_RTMT   판매상품 · 퇴직연금
      /process/HP_PBANO_PDT_NSP_INDV  판매중지상품 · 개인연금
      /process/HP_PBANO_PDT_NSP_RTMT  판매중지상품 · 퇴직연금
  - 문서: POST /process/mFileDownload {pFilePath, pFidwSeq}
          화면의 onDownload(filecors, seq, '#n') 과 동일. #1 요약서 / #2 방법서 / #3 약관
"""

from __future__ import annotations

from datetime import date

from crawler.adapters.common import clean, decode_body, js_call_args, parse_period, soup, table_rows
from crawler.base_adapter import BaseInsurerAdapter, FetchResult
from crawler.http_client import AccessDeniedError
from models.document import Document, DownloadStatus
from models.product_version import ProductVersion
from utils.file_utils import filename_from_content_disposition

BASE = "https://www.ibki.co.kr"
DOWNLOAD_URL = f"{BASE}/process/mFileDownload"

SCREENS = [
    ("HP_PBANO_PDT_SP_INDV", "판매중", "개인연금"),
    ("HP_PBANO_PDT_SP_RTMT", "판매중", "퇴직연금"),
    ("HP_PBANO_PDT_NSP_INDV", "판매중지", "개인연금"),
    ("HP_PBANO_PDT_NSP_RTMT", "판매중지", "퇴직연금"),
]

#: 표 열 순서(판매채널/상품명/판매기간 다음) -> 화면 표시명
DOC_COLUMNS = ["상품요약서", "사업방법서", "보험약관"]


class IBKLifeAdapter(BaseInsurerAdapter):
    code = "IBK_LIFE"
    collection_method = "STATIC_HTML - 판매/판매중지 × 개인연금/퇴직연금 4개 화면 파싱"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        versions: list[ProductVersion] = []
        for screen, status, group in SCREENS:
            versions.extend(self._collect(screen, status, group))
        self.log.info("[IBK_LIFE] 상품 버전 %d건 수집", len(versions))
        self.stats["html_rows"] = len(versions)
        return versions

    # ------------------------------------------------------------------
    def _collect(self, screen: str, status: str, group: str) -> list[ProductVersion]:
        url = f"{BASE}/process/{screen}"
        response = self.client.get(url)
        if response.status_code != 200:
            self.log.warning("[IBK_LIFE] %s 실패 HTTP %d", screen, response.status_code)
            return []
        document = soup(decode_body(response, "euc-kr"))

        out: list[ProductVersion] = []
        for table in document.select("table"):
            caption = clean(table.caption) if table.caption else ""
            if "상품" not in caption:
                continue
            # 화면마다 열 구성이 다르다(개인연금 6열 / 퇴직연금 6열이지만 문서 열이 다름).
            # 머리글을 읽어 열 위치를 결정하고, 행은 오른쪽부터 정렬한다
            # (rowspan 으로 판매채널/상품명 칸이 빠진 행이 있기 때문).
            headers = [clean(th) for th in table.select("thead th")] or [clean(th) for th in table.select("th")]
            if not headers:
                continue
            channel = ""
            product_name = ""
            for row in table_rows(table):
                cells = row.find_all("td")
                if not cells:
                    continue
                offset = len(headers) - len(cells)
                if offset < 0:
                    continue
                mapped = dict(zip(headers[offset:], cells))
                if "판매채널" in mapped:
                    channel = clean(mapped["판매채널"])
                if "상품명" in mapped:
                    product_name = clean(mapped["상품명"])
                if "판매기간" not in mapped or not product_name:
                    continue
                version = self._to_version(url, mapped, product_name, status, group, channel, caption)
                if version is not None:
                    out.append(version)
        self.log.info("[IBK_LIFE] %s -> %d건", screen, len(out))
        return out

    def _to_version(self, url, mapped, name, status, group, channel, caption) -> ProductVersion | None:
        sale_start, sale_end = parse_period(clean(mapped["판매기간"]))
        bank = "방카슈랑스" if "방카" in caption else ""
        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=name,
            product_category=" / ".join(x for x in (group, bank or channel) if x),
            sale_status="판매중지" if sale_end else status,
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=url,
            extra={"channel": bank or channel},
        )
        if sale_start:
            version.version_key = f"{sale_start:%Y%m%d}_판매개시"

        for header, cell in mapped.items():
            # 수집 대상 3종 열만 사용한다(퇴직연금 화면의 운용관리계약서/자산관리협정서는 제외).
            if not any(k in header for k in ("약관", "방법서", "요약서")):
                continue
            label = header
            link = cell.find("a")
            if link is None:
                continue
            args = js_call_args(link.get("onclick") or "", "onDownload")
            if len(args) < 3:
                continue
            version.source_product_id = version.source_product_id or args[1]
            doc = self.make_document(
                label=label,
                filename="",
                pFilePath=args[0],
                pFidwSeq=f"{args[1]}{args[2]}",
                source_locator=f"POST|pFilePath={args[0]}|pFidwSeq={args[1]}{args[2]}",
            )
            if doc is not None:
                version.documents.append(doc)
        return version

    # ------------------------------------------------------------------
    def fetch_document(self, document: Document) -> FetchResult:
        hint = document.download_hint
        if not hint.get("pFidwSeq"):
            return FetchResult(False, DownloadStatus.NO_DOCUMENT_LINK, reason="pFidwSeq 없음")
        try:
            response = self.client.post(
                DOWNLOAD_URL,
                data={"pFilePath": hint.get("pFilePath", ""), "pFidwSeq": hint["pFidwSeq"]},
                headers={"Referer": self.base_url or BASE},
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
