"""신한라이프 Adapter.

수집 방식: JSON_API (docs/sites/SHINHAN_LIFE.md)
  - config URL(cdhi0010.do)은 공시실 메인입니다. 실제 목록 화면(resolved_disclosure_url)
      판매중 상품   /hp/cdhi0030.do
      판매중지 상품 /hp/cdhi0040t01.do
  - 목록: POST /co/wcms/nodeInfoListPage.pwkjson
      body = {"elData":{catId, pageSize, pageIndex, method:"selectListGoods",
                        meta06:"TRUE"(판매중)|"FALSE"(판매중지), scrnId},
              "userHeader":{scrnId, appliDtptDutjCd:"DH"}}
      **필수 헤더**: `x-ajax-call: true`, `proworks-body: Y`
      (없으면 `ERROR.SYS.002` 로 실패 — 실측)
  - 응답 필드: meta02 판매채널 / meta03 구분 / meta04 상품코드 / meta05 상품명
              meta07 판매개시일시 / meta08 판매종료일시
              meta09 상품요약서 / meta10 사업방법서 / meta11 약관 (모두 /repo/... 경로)
  - 문서: POST https://www.shinhanlife.co.kr/bizxpress{경로에서 /repo/DigitalPlattform 제거}
"""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import quote

from crawler.base_adapter import BaseInsurerAdapter, FetchResult
from crawler.http_client import AccessDeniedError
from models.document import Document, DownloadStatus
from models.product_version import ProductVersion
from utils.date_utils import parse_date
from utils.file_utils import filename_from_content_disposition

BASE = "https://www.shinhanlife.co.kr"
LIST_URL = f"{BASE}/co/wcms/nodeInfoListPage.pwkjson"
DOWNLOAD_PREFIX = f"{BASE}/bizxpress"
REPO_PREFIX = "/repo/DigitalPlattform"

CAT_ID = "M160991914330045272"
SCREENS = [("cdhi0030", "TRUE", "판매중"), ("cdhi0040t01", "FALSE", "판매중지")]
PAGE_SIZE = 100

#: 응답 필드 -> 화면 표시명
DOC_FIELDS = [("meta11", "약관"), ("meta10", "사업방법서"), ("meta09", "상품요약서")]


class ShinhanLifeAdapter(BaseInsurerAdapter):
    code = "SHINHAN_LIFE"
    collection_method = "JSON_API - nodeInfoListPage.pwkjson 판매/판매중지 페이지네이션"

    def _headers(self, scrn_id: str) -> dict:
        return {
            "Referer": f"{BASE}/hp/{scrn_id}.do",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "x-ajax-call": "true",
            "proworks-body": "Y",
            "proworks-lang": "ko",
        }

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        versions: list[ProductVersion] = []
        for scrn_id, meta06, status in SCREENS:
            versions.extend(self._collect(scrn_id, meta06, status))
        self.log.info("[SHINHAN_LIFE] 상품 버전 %d건 수집", len(versions))
        self.stats["api_rows"] = len(versions)
        return versions

    # ------------------------------------------------------------------
    def _collect(self, scrn_id: str, meta06: str, status: str) -> list[ProductVersion]:
        out: list[ProductVersion] = []
        page = 1
        total = None
        while True:
            payload = {
                "elData": {"catId": CAT_ID, "pageSize": PAGE_SIZE, "pageIndex": page,
                           "method": "selectListGoods", "meta02": "", "meta03": "",
                           "title": "", "meta06": meta06, "scrnId": scrn_id},
                "userHeader": {"scrnId": scrn_id, "appliDtptDutjCd": "DH"},
            }
            response = self.client.post(
                LIST_URL, content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers=self._headers(scrn_id),
            )
            if response.status_code != 200:
                self.log.warning("[SHINHAN_LIFE] %s page=%d 실패 HTTP %d", scrn_id, page, response.status_code)
                break
            try:
                el = (response.json() or {}).get("elData") or {}
            except ValueError:
                self.log.warning("[SHINHAN_LIFE] %s page=%d JSON 해석 실패", scrn_id, page)
                break
            rows = el.get("nodeInfoVoList") or []
            if total is None:
                total = el.get("listCount")
                self.log.info("[SHINHAN_LIFE] %s -> 전체 %s건", status, total)
            if not rows:
                break
            for row in rows:
                version = self._to_version(row, scrn_id, status)
                if version is not None:
                    out.append(version)
            if len(rows) < PAGE_SIZE:
                break
            page += 1
        self.log.info("[SHINHAN_LIFE] %s -> %d건", status, len(out))
        return out

    def _to_version(self, row: dict, scrn_id: str, status: str) -> ProductVersion | None:
        name = str(row.get("meta05") or "").strip()
        if not name:
            return None
        sale_start = parse_date(str(row.get("meta07") or "")[:8])
        sale_end = parse_date(str(row.get("meta08") or "")[:8])
        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=name,
            product_category=" / ".join(
                x for x in (str(row.get("meta03") or ""), str(row.get("meta02") or "")) if x
            ),
            source_product_id=str(row.get("meta04") or row.get("ndId") or ""),
            sale_status="판매중지" if sale_end else status,
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=f"{BASE}/hp/{scrn_id}.do",
            extra={"ndId": row.get("ndId"), "채널": row.get("meta02")},
        )
        if sale_start:
            version.version_key = f"{sale_start:%Y%m%d}_판매개시"

        for field, label in DOC_FIELDS:
            path = str(row.get(field) or "").strip()
            if not path:
                continue
            doc = self.make_document(
                label=label,
                filename=path.rsplit("/", 1)[-1],
                repoPath=path,
            )
            if doc is not None:
                version.documents.append(doc)
        return version

    # ------------------------------------------------------------------
    def fetch_document(self, document: Document) -> FetchResult:
        path = document.download_hint.get("repoPath")
        if not path:
            return FetchResult(False, DownloadStatus.NO_DOCUMENT_LINK, reason="repoPath 없음")
        url = DOWNLOAD_PREFIX + quote(path.replace(REPO_PREFIX, "", 1))
        try:
            response = self.client.post(url, headers={"Referer": f"{BASE}/hp/cdhi0030.do"})
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
            final_url=url,
        )
