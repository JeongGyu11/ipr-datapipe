"""하나손해보험 Adapter.

수집 방식: JSON_API 4단계 드릴다운 (docs/sites/HANA_NON_LIFE.md)
  STEP1 POST /w/disclosure/product/getSaleStepOne.json   {sSaleYn}
        → 보험종류(자동차/일반/장기) × 세부구분
  STEP2 POST /w/disclosure/product/getSaleStepTwo.json   {sSaleYn, sInsType, sInsDtlType}
        → 상품 목록
  STEP3 POST /w/disclosure/product/getSaleStepThree.json {…상품 키…}
        → 판매기간 목록(nSeqNo)
  STEP4 POST /w/disclosure/product/getSaleStepFour.json  {sSaleYn, nSeqNo}
        → sPolicyFileID(약관) / sBizFileID(사업방법서) / sSummaryFileID(상품요약서)
  문서  GET /download/{fileID}
"""

from __future__ import annotations

from datetime import date

from crawler.adapters.common import json_post
from crawler.base_adapter import BaseInsurerAdapter
from models.document import Document
from models.product_version import ProductVersion
from utils.date_utils import parse_date

BASE = "https://m.hanainsure.co.kr"
PAGE = {"Y": f"{BASE}/w/disclosure/product/saleProduct", "N": f"{BASE}/w/disclosure/product/saleStopProduct"}
STEP1 = f"{BASE}/w/disclosure/product/getSaleStepOne.json"
STEP2 = f"{BASE}/w/disclosure/product/getSaleStepTwo.json"
STEP3 = f"{BASE}/w/disclosure/product/getSaleStepThree.json"
STEP4 = f"{BASE}/w/disclosure/product/getSaleStepFour.json"
DOWNLOAD = f"{BASE}/download/"

#: STEP4 응답 필드 -> 화면 표시명
DOC_FIELDS = [("sPolicyFileID", "약관"), ("sBizFileID", "사업방법서"), ("sSummaryFileID", "상품요약서")]


class HanaNonLifeAdapter(BaseInsurerAdapter):
    code = "HANA_NON_LIFE"
    collection_method = "JSON_API - getSaleStep1~4 드릴다운(판매/판매중지)"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        versions: list[ProductVersion] = []
        for sale_yn, status in (("Y", "판매중"), ("N", "판매중지")):
            versions.extend(self._collect(sale_yn, status))
        self.log.info("[HANA_NON_LIFE] 상품 버전 %d건 수집", len(versions))
        self.stats["api_rows"] = len(versions)
        return versions

    # ------------------------------------------------------------------
    def _call(self, url: str, payload: dict, sale_yn: str) -> list:
        response = json_post(self.client, url, payload, referer=PAGE[sale_yn])
        if response.status_code != 200:
            self.log.warning("[HANA_NON_LIFE] %s 실패 HTTP %d", url, response.status_code)
            return []
        try:
            body = (response.json() or {}).get("body")
        except ValueError:
            return []
        if body is None:
            return []
        return body if isinstance(body, list) else [body]

    def _collect(self, sale_yn: str, status: str) -> list[ProductVersion]:
        out: list[ProductVersion] = []
        categories = self._call(STEP1, {"sSaleYn": sale_yn}, sale_yn)
        for category in categories:
            products = self._call(
                STEP2,
                {
                    "sSaleYn": sale_yn,
                    "sInsType": str(category.get("sInsType")),
                    "sInsDtlType": str(category.get("sInsDtlType")),
                },
                sale_yn,
            )
            limit = self.runtime_options.get("max_products")
            if limit and len(products) > int(limit):
                self.stats["coverage_capped"] = True
                self.stats["products_skipped"] = int(self.stats.get("products_skipped", 0)) + len(products) - int(limit)
                products = products[: int(limit)]
            self.log.info("[HANA_NON_LIFE] %s / %s %s -> 상품 %d건", status,
                          category.get("sInsTypeName"), category.get("sInsDtlTypeName"), len(products))
            for product in products:
                out.extend(self._product_versions(sale_yn, status, category, product))
        return out

    def _product_versions(self, sale_yn, status, category, product) -> list[ProductVersion]:
        payload = {
            "sSaleYn": sale_yn,
            "sInsType": str(category.get("sInsType")),
            "sInsDtlType": str(category.get("sInsDtlType")),
            "sPrdKeyID": str(product.get("sPrdKeyID") or ""),
            "sSpcType": str(product.get("sSpcType") or ""),
            "sPrdType": str(product.get("sPrdType") or ""),
            "sPrdCd": str(product.get("sPrdCd") or ""),
            "RPSPDCD": str(product.get("rpspdcd") or product.get("RPSPDCD") or ""),
            "UNTPDCD": str(product.get("untpdcd") or product.get("UNTPDCD") or ""),
        }
        # STEP3 응답에 이미 판매기간(sSaleStrDt/sSaleEndDt)이 들어 있으므로
        # 대상 월 판정은 여기서 끝난다. 문서 링크(STEP4)는 대상 월로 **선정된 버전**에 대해서만
        # collect_documents() 에서 조회한다(CrawlerManager 가 선정 후 호출).
        periods = self._call(STEP3, payload, sale_yn)
        out: list[ProductVersion] = []
        for period in periods:
            seq_no = period.get("nSeqNo")
            if seq_no is None:
                continue
            sale_start = parse_date(period.get("sSaleStrDt"))
            sale_end = parse_date(period.get("sSaleEndDt"))
            version = ProductVersion(
                company_code=self.code,
                company_name=self.name,
                storage_name=self.company.storage_name,
                product_name_raw=str(product.get("sPrdNm") or "").strip(),
                product_category=" / ".join(
                    x for x in (str(category.get("sInsTypeName") or ""), str(category.get("sInsDtlTypeName") or "")) if x
                ),
                source_product_id=str(product.get("sPrdCd") or product.get("sPrdKeyID") or ""),
                sale_status="판매중지" if sale_end else status,
                sale_start_date=sale_start,
                sale_end_date=sale_end,
                source_page_url=PAGE[sale_yn],
                extra={"nSeqNo": seq_no, "sSaleYn": sale_yn},
            )
            if sale_start:
                version.version_key = f"{sale_start:%Y%m%d}_판매개시"
            out.append(version)
        return out

    # ------------------------------------------------------------------
    def collect_documents(self, product_version: ProductVersion) -> list[Document]:
        """선정된 버전에 대해서만 STEP4 로 문서 링크를 조회한다."""
        if product_version.documents:
            return product_version.documents
        seq_no = product_version.extra.get("nSeqNo")
        sale_yn = product_version.extra.get("sSaleYn", "Y")
        if seq_no is None:
            return []
        details = self._call(STEP4, {"sSaleYn": sale_yn, "nSeqNo": seq_no}, sale_yn)
        if not details:
            return []
        info = details[0]
        if not product_version.product_name_raw:
            product_version.product_name_raw = str(info.get("sPrdNm") or "").strip()
        for field, label in DOC_FIELDS:
            file_id = str(info.get(field) or "").strip()
            if not file_id:
                continue
            doc = self.make_document(label=label, url=DOWNLOAD + file_id, filename="")
            if doc is not None:
                product_version.documents.append(doc)
        return product_version.documents
