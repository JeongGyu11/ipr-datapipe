"""미래에셋생명 Adapter.

수집 방식: JSON_API (docs/sites/MIRAE_LIFE.md)
  - 목록: POST /micro/disclosure/selectWorkDvsnDataPaging.do
          {workDvsn=D, text1=판매중인상품|판매중지상품, text2=분류, text3=상품명, pageNum}
          → list[].jsonData 안에 cell0~cell7 이 문자열 JSON 으로 들어 있음
            cell0 분류 / cell1 상품명 / cell2 판매시작일 / cell3 판매종료일
            cell4 상품요약서 / cell5 약관 / cell6 사업방법서 / cell7 파일 경로
  - 문서: POST /micro/cmmnFileDown.do
          {pathType=gongci_u1, filePath=/uploadwas/life{cell7}, fileName, orgFileName}

주의: ``Accept: application/json`` 헤더가 없으면 서버가 HTTP 404 를 돌려줍니다(실측).
"""

from __future__ import annotations

import json
import re
from datetime import date

from crawler.base_adapter import BaseInsurerAdapter, FetchResult
from crawler.http_client import AccessDeniedError
from models.document import Document, DownloadStatus
from models.product_version import ProductVersion
from utils.date_utils import overlaps_month, parse_date
from utils.file_utils import filename_from_content_disposition

BASE = "https://life.miraeasset.com"
PAGE_URL = f"{BASE}/micro/disclosure/product/PC-HO-080301-000000.do"
LIST_URL = f"{BASE}/micro/disclosure/selectWorkDvsnDataPaging.do"
DOWNLOAD_URL = f"{BASE}/micro/cmmnFileDown.do"

AJAX_HEADERS = {
    "Referer": PAGE_URL,
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

#: 시트별 cell 매핑 (화면 스크립트 selectList() 의 주석/분기와 동일)
#   판매중인상품 : cell4 상품요약서 / cell5 약관 / cell6 사업방법서 / cell7 경로
#   판매중지상품 : cell4 최종판매일 / cell5 상품요약서 / cell6 약관 / cell7 사업방법서 / cell8 경로
DOC_CELLS = {
    "판매중인상품": ([("cell4", "상품요약서"), ("cell5", "약관"), ("cell6", "사업방법서")], "cell7"),
    "판매중지상품": ([("cell5", "상품요약서"), ("cell6", "약관"), ("cell7", "사업방법서")], "cell8"),
}

TABS = [("판매중인상품", "판매중"), ("판매중지상품", "판매중지")]
MAX_PAGES = 200


def _split_file_names(value: object) -> list[str]:
    """Split a document cell into the individual server-side filenames.

    The disclosure API occasionally concatenates multiple attachments in one
    cell, separated by CR/LF (for example two policy PDFs published for the
    same product/version).  Treating that value as one filename makes the
    download endpoint return its HTML error page.  Keep all other characters,
    including spaces and Korean punctuation, unchanged.
    """

    return [part.strip() for part in re.split(r"[\r\n]+", str(value or "")) if part.strip()]


class MiraeLifeAdapter(BaseInsurerAdapter):
    code = "MIRAE_LIFE"
    collection_method = "JSON_API - selectWorkDvsnDataPaging.do 판매중/판매중지 전량 조회"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        self.stats["status_coverage_complete"] = False
        self._status_coverage_complete = True
        self.stats.update(
            api_rows=0,
            raw_rows=0,
            materialized_rows=0,
            filtered_rows=0,
            unknown_dates=0,
            api_calls=0,
        )
        versions: list[ProductVersion] = []
        for text1, status in TABS:
            versions.extend(self._collect(text1, status, start_date, end_date))
        self.log.info("[MIRAE_LIFE] 상품 버전 %d건 수집", len(versions))
        self.stats["status_coverage_complete"] = bool(self._status_coverage_complete)
        return versions

    # ------------------------------------------------------------------
    def _collect(
        self,
        text1: str,
        status: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[ProductVersion]:
        out: list[ProductVersion] = []
        seen: set[str] = set()
        exhausted = False
        for page in range(MAX_PAGES):
            response = self.client.post(
                LIST_URL,
                data={"workDvsn": "D", "text1": text1, "text2": "", "text3": "", "pageNum": str(page)},
                headers=AJAX_HEADERS,
            )
            self.stats["api_calls"] = int(self.stats.get("api_calls", 0)) + 1
            if response.status_code == 403:
                raise AccessDeniedError(f"미래에셋생명 {text1} page={page} HTTP 403")
            if response.status_code != 200:
                raise RuntimeError(f"미래에셋생명 {text1} page={page} HTTP {response.status_code}")
            try:
                payload = response.json()
            except ValueError:
                raise RuntimeError(f"미래에셋생명 {text1} page={page} JSON 해석 실패") from None
            if not isinstance(payload, dict):
                raise RuntimeError(f"미래에셋생명 {text1} page={page} 응답 envelope가 객체가 아닙니다")
            if "list" not in payload or not isinstance(payload["list"], list):
                raise RuntimeError(f"미래에셋생명 {text1} page={page} list가 누락되었거나 배열이 아닙니다")
            rows = payload["list"]
            if any(not isinstance(row, dict) for row in rows):
                raise RuntimeError(f"미래에셋생명 {text1} page={page} list 항목이 객체가 아닙니다")
            self.stats["api_rows"] = int(self.stats.get("api_rows", 0)) + len(rows)
            if not rows:
                exhausted = True
                break
            # 페이지 정렬/캐시 영향으로 중복 행만 반환되는 페이지가 있어도
            # 마지막 페이지로 간주하지 않는다. 빈 응답에서만 종료한다.
            for row in rows:
                seen_key = self._row_seen_key(row)
                if seen_key in seen:
                    continue
                seen.add(seen_key)
                self.stats["raw_rows"] = int(self.stats.get("raw_rows", 0)) + 1
                cells, sale_start, sale_end = self._row_metadata(row)
                if not cells or not str(cells.get("cell1") or "").strip():
                    self.stats["filtered_rows"] = int(self.stats.get("filtered_rows", 0)) + 1
                    continue
                if sale_start is None:
                    self.stats["unknown_dates"] = int(self.stats.get("unknown_dates", 0)) + 1
                active_match = bool(self._active_status_rows) and self.matches_active_status_reference(
                    source_product_id=row.get("seq"),
                    product_name=cells.get("cell1"),
                    sale_start_date=sale_start,
                )
                if not (
                    self._is_candidate(sale_start, sale_end, start_date, end_date)
                    or active_match
                ):
                    self.stats["filtered_rows"] = int(self.stats.get("filtered_rows", 0)) + 1
                    continue
                version = self._to_version(row, status, text1, cells=cells)
                if version is not None:
                    out.append(version)
                    self.stats["materialized_rows"] = int(self.stats.get("materialized_rows", 0)) + 1
        if not exhausted and hasattr(self, "_status_coverage_complete"):
            self._status_coverage_complete = False
        self.log.info("[MIRAE_LIFE] %s -> %d건", text1, len(out))
        return out

    @staticmethod
    def _row_seen_key(row: dict) -> str:
        """목록 페이지 중복 제거용 안정 키를 만든다.

        ``seq``가 없는 레거시/부분 응답은 ``None`` 하나로 묶으면 서로 다른
        상품이 사라질 수 있다. 그런 행은 JSON 전체를 정렬 직렬화해 완전히
        동일한 행만 dedupe하고, ``pSeq``/``jsonData``를 포함한 모든 필드를
        보존한다.
        """
        seq = row.get("seq") if isinstance(row, dict) else None
        if seq is not None and str(seq).strip():
            return "seq:" + str(seq).strip()
        try:
            signature = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        except (TypeError, ValueError):
            signature = repr(row)
        return "row:" + signature

    def _row_metadata(self, row: dict) -> tuple[dict, date | None, date | None]:
        try:
            cells = json.loads(row.get("jsonData") or "{}")
        except (TypeError, ValueError):
            raise RuntimeError("미래에셋생명 목록 jsonData JSON 해석 실패") from None
        if not isinstance(cells, dict):
            raise RuntimeError("미래에셋생명 목록 jsonData가 객체가 아닙니다")
        # 상품명과 날짜/문서 셀은 화면 응답의 고정 envelope이다. cell 값이
        # 없더라도 빈 문자열은 유효한 상품 메타데이터로 허용하지만 key 자체
        # 누락은 서버 구조 변경/오류이므로 수집 실패로 처리한다.
        required = {"cell0", "cell1", "cell2", "cell3"}
        if not required.issubset(cells):
            missing = ",".join(sorted(required - set(cells)))
            raise RuntimeError(f"미래에셋생명 목록 jsonData 필수 cell 누락: {missing}")
        return cells, parse_date(cells.get("cell2")), parse_date(cells.get("cell3"))

    def _is_candidate(
        self,
        sale_start: date | None,
        sale_end: date | None,
        start_date: date | None,
        end_date: date | None,
    ) -> bool:
        if start_date is None or end_date is None:
            return True
        mode = str(getattr(self.config, "date_selection_mode", "new_or_revised") or "new_or_revised")
        # 시작일 미상 행은 종료일이 있더라도 목록 단계에서 버리지 않고
        # 공통 selector가 수동검토 여부를 결정한다.
        if sale_start is None:
            return True
        if mode == "overlap":
            return overlaps_month(sale_start, sale_end, start_date, end_date)
        if mode != "new_or_revised":
            raise ValueError(f"알 수 없는 date_selection.mode: {mode!r}")
        # 날짜 미상은 자동 필터링하지 않고 수동검토 대상으로 남긴다.
        return start_date <= sale_start <= end_date

    def _to_version(
        self,
        row: dict,
        status: str,
        sheet: str,
        *,
        cells: dict | None = None,
    ) -> ProductVersion | None:
        if cells is None:
            cells, _, _ = self._row_metadata(row)
        if not cells:
            return None
        name = str(cells.get("cell1") or "").strip()
        if not name:
            return None
        doc_cells, dir_key = DOC_CELLS[sheet]
        sale_start = parse_date(cells.get("cell2"))
        sale_end = parse_date(cells.get("cell3"))
        file_dir = str(cells.get(dir_key) or "").strip()

        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=name,
            product_category=str(cells.get("cell0") or ""),
            source_product_id=str(row.get("seq") or ""),
            # 판매상태는 원본 탭이 authoritative 하다. 종료일 셀은
            # 원시 metadata로 보존하며 이를 이용해 상태를 재추론하지 않는다.
            sale_status=status,
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=PAGE_URL,
            extra={"pSeq": row.get("pSeq"), "fileDir": file_dir},
        )
        if sale_start:
            version.version_key = f"{sale_start:%Y%m%d}_판매개시"

        for key, label in doc_cells:
            file_names = _split_file_names(cells.get(key))
            if not file_names or not file_dir:
                continue
            for attachment_ordinal, file_name in enumerate(file_names, start=1):
                doc = self.make_document(
                    label=label,
                    filename=file_name,
                    filePath="/uploadwas/life" + file_dir,
                    fileName=file_name,
                    attachmentOrdinal=attachment_ordinal,
                    source_locator=(
                        f"POST|filePath=/uploadwas/life{file_dir}|"
                        f"fileName={file_name}|attachmentOrdinal={attachment_ordinal}"
                    ),
                )
                if doc is not None:
                    version.documents.append(doc)
        return version

    # ------------------------------------------------------------------
    def fetch_document(self, document: Document) -> FetchResult:
        hint = document.download_hint
        if not hint.get("fileName"):
            return FetchResult(False, DownloadStatus.NO_DOCUMENT_LINK, reason="fileName 없음")
        payload = {
            "pathType": "gongci_u1",
            "fileName": hint["fileName"],
            "orgFileName": hint["fileName"],
            "filePath": hint.get("filePath", ""),
        }
        try:
            # The download form is submitted by the disclosure page's AJAX
            # helper.  The site rejects a plain Referer-only POST (often with
            # an HTML/404 response), so preserve the same headers as listing
            # requests, including Accept and X-Requested-With.
            response = self.client.post(DOWNLOAD_URL, data=payload, headers=AJAX_HEADERS)
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
