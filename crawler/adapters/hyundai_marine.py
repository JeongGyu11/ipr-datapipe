"""현대해상 Adapter.

수집 방식: JSON_API (docs/sites/HYUNDAI_MARINE.md)
  - 목록: POST /ajax.xhi  tranId=HHCA0310M19S  {slYn: Y|N}
          → data.hhca0051VOList 에 전체 상품 버전(판매중/판매중지 각각 1회 호출)
            prodNm, prodCatCd, slStDt, slEdDt,
            clauApnflId(약관) / userMthdApnflId(사업방법서) /
            prodSmryApnflId(상품요약서) / prodNoteApnflId(상품설명서 - 제외)
  - 파일경로: POST /ajax.xhi tranId=HHCA0310M26S {apnflId}
          → savPath, savFileNm, flExts, originalFileNm
  - 문서: GET /FileActionServlet/download/0/{savPath}/{savFileNm}.{flExts}
"""

from __future__ import annotations

from datetime import date

from crawler.adapters.common import json_post
from crawler.base_adapter import BaseInsurerAdapter, FetchResult
from crawler.http_client import AccessDeniedError
from models.document import Document, DownloadStatus
from models.product_version import ProductVersion
from utils.date_utils import parse_date
from utils.file_utils import filename_from_content_disposition

BASE = "https://www.hi.co.kr"
PAGE_URL = f"{BASE}/serviceAction.do?view=bin%2FPA%2F03%2FHHPA03020M"
AJAX_URL = f"{BASE}/ajax.xhi"
FILE_URL = f"{BASE}/FileActionServlet/download/0"

LIST_TRAN = "HHCA0310M19S"
FILE_TRAN = "HHCA0310M26S"

#: 응답 필드 -> 화면 표시명
DOC_FIELDS = [
    ("clauApnflId", "약관"),
    ("userMthdApnflId", "사업방법서"),
    ("prodSmryApnflId", "상품요약서"),
    ("prodNoteApnflId", "상품설명서"),   # 기본 제외 대상
]

#: prodCatCd 앞 2자리 -> 상품 구분(화면 카테고리)
CATEGORY_NAMES = {"01": "일반보험", "02": "자동차보험", "03": "장기보험", "04": "기타", "05": "기타"}


class HyundaiMarineAdapter(BaseInsurerAdapter):
    code = "HYUNDAI_MARINE"
    collection_method = "JSON_API - ajax.xhi HHCA0310M19S 전량 조회 + 파일경로 조회"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        versions: list[ProductVersion] = []
        for sl_yn, status in (("Y", "판매중"), ("N", "판매중지")):
            versions.extend(self._collect(sl_yn, status))
        self.log.info("[HYUNDAI_MARINE] 상품 버전 %d건 수집", len(versions))
        self.stats["api_rows"] = len(versions)
        return versions

    # ------------------------------------------------------------------
    def _request(self, tran_id: str, request: dict, timeout: float | None = None):
        payload = {
            "header": {
                "gId": "",
                "tranId": tran_id,
                "channelId": "HI-HOME",
                "clientIp": "127.0.0.1",
                "menuId": "",
                "loginId": None,
            },
            "request": request,
        }
        return json_post(self.client, AJAX_URL, payload, referer=PAGE_URL, timeout=timeout)

    def _collect(self, sl_yn: str, status: str) -> list[ProductVersion]:
        response = self._request(LIST_TRAN, {"slYn": sl_yn}, timeout=max(self.config.timeout, 120))
        if response.status_code != 200:
            self.log.warning("[HYUNDAI_MARINE] slYn=%s 실패 HTTP %d", sl_yn, response.status_code)
            return []
        try:
            data = (response.json() or {}).get("data") or {}
        except ValueError:
            self.log.warning("[HYUNDAI_MARINE] slYn=%s JSON 해석 실패", sl_yn)
            return []
        rows = data.get("hhca0051VOList") or []
        self.log.info("[HYUNDAI_MARINE] slYn=%s -> %d행", sl_yn, len(rows))

        out: list[ProductVersion] = []
        for row in rows:
            version = self._to_version(row, status)
            if version is not None:
                out.append(version)
        return out

    def _to_version(self, row: dict, status: str) -> ProductVersion | None:
        name = str(row.get("prodNm") or "").strip()
        if not name:
            return None
        sale_start = parse_date(str(row.get("slStDt") or "").strip())
        sale_end = parse_date(str(row.get("slEdDt") or "").strip())
        cat_code = str(row.get("prodCatCd") or "")
        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=name,
            product_category=CATEGORY_NAMES.get(cat_code[:2], cat_code),
            source_product_id=str(row.get("insCd") or row.get("seqno") or ""),
            sale_status="판매중지" if sale_end else status,
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=PAGE_URL,
            extra={"prodCatCd": cat_code},
        )
        if sale_start:
            version.version_key = f"{sale_start:%Y%m%d}_판매개시"

        for field, label in DOC_FIELDS:
            apnfl_id = str(row.get(field) or "").strip()
            if not apnfl_id:
                continue
            doc = self.make_document(
                label=label,
                filename="",
                apnflId=apnfl_id,
                source_locator=f"POST|apnflId={apnfl_id}",
            )
            if doc is not None:
                version.documents.append(doc)
        return version

    # ------------------------------------------------------------------
    def fetch_document(self, document: Document) -> FetchResult:
        apnfl_id = document.download_hint.get("apnflId")
        if not apnfl_id:
            return FetchResult(False, DownloadStatus.NO_DOCUMENT_LINK, reason="apnflId 없음")
        try:
            meta = self._request(FILE_TRAN, {"apnflId": apnfl_id})
            info = (meta.json() or {}).get("data") or {}
        except AccessDeniedError as exc:
            return FetchResult(False, DownloadStatus.ACCESS_DENIED, reason=str(exc))
        except Exception as exc:  # noqa: BLE001
            return FetchResult(False, DownloadStatus.DOWNLOAD_FAILED, reason=f"{type(exc).__name__}: {exc}")

        sav_path = str(info.get("savPath") or "").strip("/")
        sav_name = str(info.get("savFileNm") or "").strip()
        exts = str(info.get("flExts") or "pdf").strip()
        if not (sav_path and sav_name):
            return FetchResult(False, DownloadStatus.NO_DOCUMENT_LINK, reason="파일 경로 응답 없음")

        url = f"{FILE_URL}/{sav_path}/{sav_name}.{exts}"
        try:
            response = self.client.get(url, headers={"Referer": PAGE_URL})
        except AccessDeniedError as exc:
            return FetchResult(False, DownloadStatus.ACCESS_DENIED, reason=str(exc))
        except Exception as exc:  # noqa: BLE001
            return FetchResult(False, DownloadStatus.DOWNLOAD_FAILED, reason=f"{type(exc).__name__}: {exc}")

        original = (
            str(info.get("originalFileNm") or "")
            or filename_from_content_disposition(response.headers.get("content-disposition", ""))
        )
        return FetchResult(
            ok=response.status_code == 200,
            status=DownloadStatus.SUCCESS if response.status_code == 200 else DownloadStatus.INVALID_RESPONSE,
            content=response.content,
            content_type=response.headers.get("content-type", ""),
            original_filename=original,
            http_status=response.status_code,
            final_url=url,
        )
