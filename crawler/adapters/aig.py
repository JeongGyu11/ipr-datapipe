"""AIG손해보험 Adapter.

수집 방식: 단일 게이트웨이 `POST /bomservice.do` 평문 JSON (docs/sites/AIG.md)

  목록  POST /bomservice.do
        {"header":{"txCode":"DPWOS002"},
         "payload":{"useYn":"Y|N","pancLrgCfcd":"01","pancMdimCfcd":"","prodCd":"","pdnm":""}}
        → payload.prodDisclosureList
        useYn=Y 판매중(/wo/dpwot001.html?menuId=MS702)
        useYn=N 판매중지(/wo/dpwot002.html?menuId=MS703)

  문서  GET /downLoadFiles.do?fileId=&fileSeq=&fileType=&fileGb=&viewType=
        화면의 fileDownLoad(fileId, fileSeq) 가 만드는 URL 과 동일하다.
        Content-Disposition 의 fileName 은 퍼센트 인코딩된 UTF-8 이라 공통 파서가 그대로 처리한다.

주의: 목록 응답의 상품설명서(prodMadcFileNm)는 수집 대상 3종이 아니므로 넣지 않는다.
"""

from __future__ import annotations

from datetime import date

from crawler.base_adapter import BaseInsurerAdapter
from models.product_version import ProductVersion
from utils.date_utils import parse_date

BASE = "https://www.aig.co.kr"
GATEWAY = f"{BASE}/bomservice.do"
DOWNLOAD_URL = f"{BASE}/downLoadFiles.do"
TX_LIST = "DPWOS002"

#: (useYn, 판매상태, 화면 URL) - 두 화면은 useYn 만 다르고 나머지 파라미터가 같다.
MODES = [
    ("Y", "판매중", f"{BASE}/wo/dpwot001.html?menuId=MS702"),
    ("N", "판매중지", f"{BASE}/wo/dpwot002.html?menuId=MS703"),
]

#: (파일ID 필드, 파일순번 필드, 화면 표시명)
DOC_FIELDS = [
    ("clauFileId", "clauFileSeqn", "약관"),
    ("bzMthdFileId", "bzMthdFileSeqn", "사업방법서"),
    ("prodSmryFileId", "prodSmryFileSeqn", "상품요약서"),
]


class AIGAdapter(BaseInsurerAdapter):
    code = "AIG"
    collection_method = "JSON_API - bomservice.do 게이트웨이(txCode=DPWOS002) 판매중/판매중지 2회 조회"
    legacy_ssl = True

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        versions: list[ProductVersion] = []
        for use_yn, status, page_url in MODES:
            rows = self._list(use_yn, page_url)
            self.log.info("[AIG] %s -> %d건", status, len(rows))
            for row in rows:
                version = self._version(row, status, page_url)
                if version is not None:
                    versions.append(version)
        self.log.info("[AIG] 상품 버전 %d건 수집", len(versions))
        self.stats["api_rows"] = len(versions)
        return versions

    # ------------------------------------------------------------------
    def _list(self, use_yn: str, page_url: str) -> list[dict]:
        """상품공시 목록을 받아온다. 화면과 동일한 페이로드를 쓴다."""
        payload = {
            "useYn": use_yn,
            "pancLrgCfcd": "01",
            "pancMdimCfcd": "",
            "prodCd": "",
            "pdnm": "",
        }
        response = self.client.post(
            GATEWAY,
            json={"header": {"txCode": TX_LIST}, "payload": payload},
            headers={"Referer": page_url, "Content-Type": "application/json; charset=UTF-8"},
        )
        if response.status_code != 200:
            self.log.warning("[AIG] 목록 실패 HTTP %d (useYn=%s)", response.status_code, use_yn)
            return []
        body = response.json()
        result_code = (body.get("header") or {}).get("RESULT_CODE")
        if result_code != "0":
            self.log.warning("[AIG] 목록 응답 코드 %s (useYn=%s)", result_code, use_yn)
            return []
        return (body.get("payload") or {}).get("prodDisclosureList") or []

    # ------------------------------------------------------------------
    def _version(self, row: dict, status: str, page_url: str) -> ProductVersion | None:
        product_name = (row.get("pdnm") or "").strip()
        if not product_name:
            return None

        sale_start = parse_date((row.get("stDt") or "")[:10])
        sale_end = parse_date((row.get("endt") or "")[:10])
        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=product_name,
            product_category=(row.get("mclfNm") or "").strip(),
            source_product_id=str(row.get("prodCd") or row.get("pancId") or ""),
            sale_status="판매중지" if sale_end else status,
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=page_url,
        )
        if sale_start:
            version.version_key = f"{sale_start:%Y%m%d}_판매개시"

        for id_field, seq_field, label in DOC_FIELDS:
            file_id = str(row.get(id_field) or "").strip()
            file_seq = str(row.get(seq_field) or "").strip()
            if not file_id or not file_seq:
                continue
            document = self.make_document(
                label=label,
                url=f"{DOWNLOAD_URL}?fileId={file_id}&fileSeq={file_seq}"
                    f"&fileType=&fileGb=&viewType=",
            )
            if document is not None:
                version.documents.append(document)
        return version
