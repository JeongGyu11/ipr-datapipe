"""흥국생명 Adapter.

수집 방식: FORM_POST + 구분자 응답 파싱 (docs/sites/HEUNGKUK_LIFE.md)
  - 상품명 목록 : POST /front/public/saleProductAjax.do
        searchFlgSale=Y(판매) / N(판매중지)
        searchCdPublicPrtType1 = I101 개인 / I102 단체 / I103 방카슈랑스
        searchCdPublicPrtType2 = I201 연금 … I209 기타
        → 응답 블록0 에 상품명 목록(`%|%` 구분)
  - 상품 상세 : 같은 엔드포인트에 searchCdPublicPrtType3 = 상품명
        → 응답 블록2 에 판매기간·문서 토큰(`%|%` 행, `%,%` 열)
  - 문서 : POST /servlet/DownLoadEnc.do  {encValue=<암호화 토큰>, + 조회 폼 필드}

응답은 EUC-KR 이며 화면 스크립트가 쓰는 escape(encodeURIComponent(x)) 인코딩을
그대로 재현해야 한글 상품명이 매칭됩니다.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import quote

from crawler.adapters.common import clean, decode_body, parse_period
from crawler.base_adapter import BaseInsurerAdapter, FetchResult
from crawler.http_client import AccessDeniedError
from models.document import Document, DownloadStatus
from models.product_version import ProductVersion
from utils.file_utils import filename_from_content_disposition

BASE = "https://www.heungkuklife.co.kr"
PAGE_URL = f"{BASE}/front/public/saleProduct.do?searchFlgSale=Y"
LIST_URL = f"{BASE}/front/public/saleProductAjax.do"
DOWNLOAD_URL = f"{BASE}/servlet/DownLoadEnc.do"

MODES = [("Y", "판매중"), ("N", "판매중지")]
TYPE1 = [("I101", "개인"), ("I102", "단체"), ("I103", "방카슈랑스")]

#: 상세 행(`%,%` 분리)에서 문서가 위치한 인덱스 -> 화면 표시명
#: [0]=판매개시일 [1]=판매종료일 [2]=보장/상품코드 [3]=순번
#: [4]=약관 토큰 [5]=약관 파일명 [6]=사업방법서 토큰 [7]=사업방법서 파일명
#: [8]=상품요약서 토큰 [9]=상품요약서 파일명
DOC_SLOTS = [(4, 5, "약관"), (6, 7, "사업방법서"), (8, 9, "상품요약서")]


def _js_escape(text: str) -> str:
    """화면의 escape(encodeURIComponent(x)) 재현."""
    return quote(quote(text, safe=""), safe="")


class HeungkukLifeAdapter(BaseInsurerAdapter):
    code = "HEUNGKUK_LIFE"
    collection_method = "FORM_POST - saleProductAjax.do 분류별 상품명 + 상품별 판매기간 조회"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        products: list[tuple[str, str, str, str]] = []   # (flg, status, type1명, 상품명)
        seen: set[tuple[str, str]] = set()
        for flg, status in MODES:
            for type1, type1_name in TYPE1:
                for name in self._fetch_names(flg, type1):
                    key = (flg, name)
                    if key in seen:
                        continue
                    seen.add(key)
                    products.append((flg, status, type1_name, name))
        self.log.info("[HEUNGKUK_LIFE] 상품 %d건 수집, 상세 조회 시작", len(products))
        self.stats["products"] = len(products)

        limit = self.runtime_options.get("max_products")
        if limit and len(products) > int(limit):
            self.stats["coverage_capped"] = True
            self.stats["products_total"] = len(products)
            self.stats["products_skipped"] = len(products) - int(limit)
            products = products[: int(limit)]

        versions: list[ProductVersion] = []
        for index, (flg, status, type1_name, name) in enumerate(products, start=1):
            versions.extend(self._fetch_versions(flg, status, type1_name, name))
            if index % 50 == 0:
                self.log.info("[HEUNGKUK_LIFE] 상세 진행 %d/%d", index, len(products))
        self.log.info("[HEUNGKUK_LIFE] 상품 버전 %d건 수집", len(versions))
        return versions

    # ------------------------------------------------------------------
    def _post(self, flg: str, type1: str, type3: str = "") -> str:
        body = (f"searchFlgSale={flg}&beforeYn=&searchCdPublicPrtType1={type1}"
                f"&searchCdPublicPrtType2=&searchCdPublicPrtType3={_js_escape(type3)}&searchText=")
        response = self.client.post(
            LIST_URL,
            content=body,
            headers={"Referer": PAGE_URL, "X-Requested-With": "XMLHttpRequest",
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            self.log.warning("[HEUNGKUK_LIFE] 조회 실패 HTTP %d (flg=%s type1=%s)",
                             response.status_code, flg, type1)
            return ""
        return decode_body(response, "euc-kr")

    def _fetch_names(self, flg: str, type1: str) -> list[str]:
        blocks = self._post(flg, type1).split("%||%")
        if not blocks:
            return []
        names = []
        for chunk in blocks[0].split("%|%"):
            name = chunk.split("%,%")[0].strip()
            if name and name.lower() != "null":
                names.append(name)
        return names

    def _fetch_versions(self, flg, status, type1_name, name) -> list[ProductVersion]:
        blocks = self._post(flg, "", name).split("%||%")
        if len(blocks) < 3:
            return []
        out: list[ProductVersion] = []
        for row in blocks[2].split("%|%"):
            cols = row.split("%,%")
            if len(cols) < 6:
                continue
            sale_start, sale_end = parse_period(f"{clean(cols[0])} ~ {clean(cols[1])}")
            version = ProductVersion(
                company_code=self.code,
                company_name=self.name,
                storage_name=self.company.storage_name,
                product_name_raw=name,
                product_category=type1_name,
                source_product_id=clean(cols[3]) if len(cols) > 3 else "",
                sale_status="판매중지" if sale_end else status,
                sale_start_date=sale_start,
                sale_end_date=sale_end,
                source_page_url=PAGE_URL,
                version_key=f"{sale_start:%Y%m%d}_판매개시" if sale_start else "",
                extra={"보장": clean(cols[2]) if len(cols) > 2 else ""},
            )
            for token_idx, name_idx, label in DOC_SLOTS:
                if name_idx >= len(cols):
                    continue
                token = cols[token_idx].strip()
                file_name = clean(cols[name_idx])
                if not token or not file_name:
                    continue
                doc = self.make_document(
                    label=label,
                    filename=file_name,
                    encValue=token,
                    source_locator=f"POST|fileName={file_name}",
                )
                if doc is not None:
                    version.documents.append(doc)
            out.append(version)
        return out

    # ------------------------------------------------------------------
    def fetch_document(self, document: Document) -> FetchResult:
        token = document.download_hint.get("encValue")
        if not token:
            return FetchResult(False, DownloadStatus.NO_DOCUMENT_LINK, reason="encValue 없음")
        payload = {
            "searchFlgSale": "Y", "beforeYn": "",
            "searchCdPublicPrtType1": "", "searchCdPublicPrtType2": "", "searchCdPublicPrtType3": "",
            "searchText": "", "encValue": token,
        }
        try:
            response = self.client.post(DOWNLOAD_URL, data=payload, headers={"Referer": PAGE_URL})
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
