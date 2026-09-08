"""라이나생명 Adapter.

수집 방식: JSON_API 2단계 (docs/sites/LINA_LIFE.md §12)

  1) 목록  GET .../disclosure/get-product-list      (판매중)
           GET .../disclosure/get-product-endlist   (판매중지)
           파라미터 mtrtDcd = `B` 주보험 / `R` 특약
                    KliaProdClcd = 상품분류(주보험)
                    KcisInsKcd   = 보종(특약)
           → listDisclosure[] = {inscd, insureCd, insNm, sellOpnDt, sellEndDt,
                                  insRenwPrcsPsbYn, kcisInsKcd, prodPbanGrpCd, kliaProdClcd}
           **파일 정보는 없습니다.** 화면에서도 접힌 상태에는 상품명만 보입니다.

  2) 상세  GET .../disclosure/product-list-detail?insureCd=&prodPbanGrpCd=          (판매중)
           GET .../disclosure/end-product-detail?insureCd=&prodPbanGrpCd=&insRenwPrcsPsbYn=  (판매중지)
           → listDisclosure[] = {sellOpnDt, sellEndDt, productSumary, productMethod,
                                  productProvision, itemSection, trtTpCd, ...}
           화면에서 상품을 펼칠 때 호출되며 **판매기간별로 문서 3종**을 돌려줍니다.

  3) 문서  GET https://www.lina.co.kr/cms/upload/upload/docs/disclosure/{파일명}
           화면 스크립트의 openFile():
             var t = this.currentUrl + "/cms/upload/upload/docs/disclosure/" + e;

상세 조회는 상품 1건당 1회이고 상품이 4,500건이 넘으므로 `collect_documents()` 에 둡니다.
`CrawlerManager` 가 대상 월로 선정한 버전에 대해서만 호출됩니다(하나손해보험과 동일한 방식).

trtTpCd 는 종속특약 표기입니다. `02` 면 요약서·방법서가, `03` 이면 요약서가 화면에서 `-` 로
표시되며 "함께 가입하신 주보험에서 확인" 안내가 붙습니다. 수집 누락이 아니라 사이트 정책입니다.
"""

from __future__ import annotations

from datetime import date

from crawler.base_adapter import BaseInsurerAdapter
from models.product_version import ProductVersion
from utils.date_utils import parse_date

API = "https://api.lina.co.kr/public/contents/v1/disclosure/"
PAGE_URL = "https://www.lina.co.kr/disclosure/product-public-announcement/product-on-sales"
FILE_BASE = "https://www.lina.co.kr/cms/upload/upload/docs/disclosure/"

#: (목록 엔드포인트, 상세 엔드포인트, 판매상태)
SCREENS = [
    ("get-product-list", "product-list-detail", "판매중"),
    ("get-product-endlist", "end-product-detail", "판매중지"),
]
#: (mtrtDcd, 구분명, 분류 파라미터 사용 여부)
KINDS = [("B", "주보험", True), ("R", "특약", False)]
#: 주보험 상품분류 코드(실측)
PROD_CLASSES = [f"{i:02d}" for i in range(1, 13)]
#: 특약 보종 코드(실측)
INS_KINDS = [f"{i:02d}" for i in range(1, 6)]

#: 상세 응답 필드 -> 화면 표시명
DOC_FIELDS = [
    ("productProvision", "약관"),
    ("productMethod", "사업방법서"),
    ("productSumary", "상품요약서"),
]


class LinaLifeAdapter(BaseInsurerAdapter):
    code = "LINA_LIFE"
    collection_method = "JSON_API - get-product-list/endlist 목록 + 상세 지연 조회"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        versions: list[ProductVersion] = []
        seen: set[str] = set()
        for list_ep, detail_ep, status in SCREENS:
            for kind_code, kind_name, use_class in KINDS:
                codes = PROD_CLASSES if use_class else INS_KINDS
                for code in codes:
                    params = ({"KliaProdClcd": code} if use_class else {"KcisInsKcd": code})
                    for row in self._get(list_ep, mtrtDcd=kind_code, **params):
                        inscd = str(row.get("inscd") or "")
                        if inscd in seen:
                            continue
                        seen.add(inscd)
                        version = self._to_version(row, kind_name, status, detail_ep)
                        if version is not None:
                            versions.append(version)
        self.log.info("[LINA_LIFE] 상품 버전 %d건 수집", len(versions))
        self.stats["api_rows"] = len(versions)
        return versions

    # ------------------------------------------------------------------
    def collect_documents(self, version: ProductVersion):
        """대상 월로 선정된 버전에 대해서만 상세를 조회해 문서를 만든다."""
        extra = version.extra or {}
        insure_cd = str(extra.get("insureCd") or "")
        detail_ep = str(extra.get("detail_endpoint") or "")
        if not insure_cd or not detail_ep:
            return list(version.documents)

        params = {"insureCd": insure_cd, "prodPbanGrpCd": str(extra.get("prodPbanGrpCd") or "")}
        if detail_ep == "end-product-detail":
            params["insRenwPrcsPsbYn"] = str(extra.get("insRenwPrcsPsbYn") or "")
        rows = self._get(detail_ep, **params)

        row = self._match(rows, version)
        if row is None:
            self.log.info("[LINA_LIFE] 상세에서 판매기간 일치 행 없음: %s (%s)",
                          version.product_name_raw, version.version_key)
            return list(version.documents)

        documents = list(version.documents)
        for field, label in DOC_FIELDS:
            file_name = str(row.get(field) or "").strip()
            # 화면에서 '-' 로 표시되는 종속특약 항목은 파일이 없다.
            if not file_name or file_name == "-":
                continue
            document = self.make_document(label=label, url=FILE_BASE + file_name,
                                          filename=file_name)
            if document is not None:
                documents.append(document)
        return documents

    # ------------------------------------------------------------------
    @staticmethod
    def _match(rows: list[dict], version: ProductVersion) -> dict | None:
        """판매개시일이 같은 상세 행을 찾는다. 없으면 가장 최근 행."""
        target = version.sale_start_date
        if target is not None:
            for row in rows:
                if parse_date(row.get("sellOpnDt")) == target:
                    return row
        return rows[0] if rows else None

    def _get(self, endpoint: str, **params) -> list[dict]:
        query = {"mtrtDcd": "", "KliaProdClcd": "", "KcisInsKcd": "", "searchKey": "",
                 "inscd": "", "prodPbanGrpCd": "", "tabTitle": ""}
        query.update(params)
        try:
            response = self.client.get(
                API + endpoint, params=query,
                headers={"Referer": "https://www.lina.co.kr/",
                         "Accept": "application/json, text/plain, */*"},
            )
        except Exception as exc:  # noqa: BLE001 - 1건 실패가 전체를 막지 않도록
            self.log.warning("[LINA_LIFE] %s %s 실패: %s", endpoint, params, exc)
            return []
        if response.status_code != 200:
            return []
        try:
            return (response.json() or {}).get("listDisclosure") or []
        except ValueError:
            return []

    def _to_version(self, row: dict, kind_name: str, status: str,
                    detail_endpoint: str) -> ProductVersion | None:
        name = str(row.get("insNm") or "").strip()
        if not name:
            return None
        sale_start = parse_date(row.get("sellOpnDt"))
        sale_end = parse_date(row.get("sellEndDt"))
        # 99991231 은 '현재 판매중' 을 뜻하는 무기한 표기라 종료일로 쓰지 않는다.
        if sale_end and sale_end.year >= 9999:
            sale_end = None
        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=name,
            product_category=" / ".join(
                x for x in (kind_name, str(row.get("kliaProdClcd") or "")) if x
            ),
            source_product_id=str(row.get("inscd") or ""),
            sale_status="판매중지" if sale_end else status,
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=PAGE_URL,
            extra={
                "insureCd": row.get("insureCd") or str(row.get("inscd") or "")[:6],
                "prodPbanGrpCd": row.get("prodPbanGrpCd"),
                "insRenwPrcsPsbYn": row.get("insRenwPrcsPsbYn"),
                "detail_endpoint": detail_endpoint,
            },
        )
        if sale_start:
            version.version_key = f"{sale_start:%Y%m%d}_판매개시"
        return version
