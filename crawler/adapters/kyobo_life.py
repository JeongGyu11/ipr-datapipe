"""교보생명 Adapter.

수집 방식: JSON_API (docs/sites/KYOBO_LIFE.md)
  - config URL(/dgt/web/product-official/information)은 공시 안내 화면이며,
    실제 상품 목록 화면은 /dgt/web/product-official/all-product/search 입니다.
  - 목록: POST /dtc/product-official/find-allProductSearch  (JSON)
  - 상세: POST /dtc/product-official/find-allProductSearchDetail {dgtPdtPdSeqtId}
          → list(판매기간), list2(temp01=상품요약서 / temp02=약관 / temp03=사업방법서)
  - 문서: GET /file/ajax/download?fName=/dtc/pdf/mm/{파일명}
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from urllib.parse import quote

from crawler.adapters.common import json_post
from crawler.base_adapter import BaseInsurerAdapter
from crawler.detail_checkpoint_service import DetailCheckpointService
from crawler.http_client import AccessDeniedError
from models.product_version import ProductVersion
from utils.date_utils import parse_date

BASE = "https://www.kyobo.com"
SEARCH_PAGE = f"{BASE}/dgt/web/product-official/all-product/search"
LIST_URL = f"{BASE}/dtc/product-official/find-allProductSearch"
DETAIL_URL = f"{BASE}/dtc/product-official/find-allProductSearchDetail"
DOWNLOAD_URL = f"{BASE}/file/ajax/download?fName=/dtc/pdf/mm/"

#: 상세 응답 필드 -> 화면 표시명 (requestDtlCallBack 의 열 구성으로 확인)
DOC_FIELDS = [("temp01", "상품요약서"), ("temp02", "약관"), ("temp03", "사업방법서")]

PAGE_SIZE = 100
MAX_PAGES = 200


class KyoboLifeAdapter(BaseInsurerAdapter):
    code = "KYOBO_LIFE"
    collection_method = "JSON_API - find-allProductSearch + 상품별 판매기간 상세 조회"
    detail_checkpoint_filename = "detail_checkpoint.v2.jsonl"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        # 동일 인스턴스 재사용 시 이전 실행의 조건부/상세 통계가 새
        # 실행 결과를 오염시키지 않도록 수집 시작 시 초기화한다.
        self.stats.update(
            coverage_capped=False,
            status_coverage_complete=False,
            products_total=0,
            products_skipped=0,
            detail_checkpoint_attempted=0,
            detail_checkpoint_reused=0,
            detail_checkpoint_failed=0,
        )
        products = self._fetch_products()
        self.log.info("[KYOBO_LIFE] 상품 %d건 수신, 판매기간 상세 조회 시작", len(products))
        self.stats["products"] = len(products)

        limit = self.runtime_options.get("max_products")
        if limit:
            products = products[: int(limit)]
            self.stats["coverage_capped"] = True
            self.stats["status_coverage_complete"] = False
            self.stats["products_total"] = int(self.stats["products"])
            self.stats["products_skipped"] = int(self.stats["products"]) - len(products)

        versions: list[ProductVersion] = []
        checkpoint = self._checkpoint_service()
        attempted = reused = failed = 0
        for index, product in enumerate(products, start=1):
            if index % 50 == 0:
                self.log.info("[KYOBO_LIFE] 상세 진행 %d/%d", index, len(products))
            active_match = self._matches_active_product(product)
            if checkpoint is not None and not active_match:
                cached = checkpoint.reusable(product)
                if cached is not None:
                    versions.extend(cached.versions)
                    reused += 1
                    continue

            attempted += 1
            try:
                # Missing identifiers are deliberately handled as a failed
                # detail, rather than being turned into a successful empty
                # result and cached forever.
                self._require_detail_identifiers(product)
                product_versions = self._fetch_versions(product)
            except AccessDeniedError as exc:
                if checkpoint is not None:
                    checkpoint.record_failure(product, f"{type(exc).__name__}: {exc}")
                raise
            except Exception as exc:  # noqa: BLE001 - 상품 단위 재개를 위해 기록
                failed += 1
                if checkpoint is not None:
                    checkpoint.record_failure(product, f"{type(exc).__name__}: {exc}")
                self.log.warning(
                    "[KYOBO_LIFE] 상세 조회 실패 key=%s: %s", self._detail_key(product), exc
                )
                continue

            if checkpoint is not None:
                checkpoint.record_success(product, product_versions)
            versions.extend(product_versions)

        self.stats["detail_checkpoint_attempted"] = attempted
        self.stats["detail_checkpoint_reused"] = reused
        self.stats["detail_checkpoint_failed"] = failed
        if failed:
            raise RuntimeError(
                f"교보생명 상품 상세 {failed}건을 완전히 수집하지 못했습니다. "
                "완료된 상품은 체크포인트에 보존되므로 같은 기간으로 재실행해 주세요."
            )
        self.stats["status_coverage_complete"] = not bool(limit) and failed == 0
        self.log.info("[KYOBO_LIFE] 상품 버전 %d건 수집", len(versions))
        return versions

    def _matches_active_product(self, product: dict[str, Any]) -> bool:
        rows = self.active_status_rows
        if not rows:
            return False
        return self.matches_active_status_reference(
            source_product_id=product.get("dgtPdtCd") or "",
            product_name=product.get("dgtPdtAtrNm") or "",
        )

    # ------------------------------------------------------------------
    def configure_detail_checkpoint(self, root: str, scope: str = "default") -> DetailCheckpointService:
        """실행 관리자가 기간 scope를 명시해 상세 체크포인트를 켠다."""
        self.runtime_options = {
            **self.runtime_options,
            "detail_checkpoint_path": root,
            "detail_checkpoint_scope": scope,
        }
        self._detail_checkpoint = DetailCheckpointService(
            root,
            scope=scope,
            filename=self.detail_checkpoint_filename,
            key_fn=self._detail_key,
            adapter_version="KYOBO_LIFE.detail.v1",
        )
        return self._detail_checkpoint

    def _checkpoint_service(self) -> DetailCheckpointService | None:
        """옵션이 설정된 경우에만 상세 체크포인트를 활성화한다."""
        options = self.runtime_options
        root = options.get("detail_checkpoint_path")
        if not root:
            return None
        if not hasattr(self, "_detail_checkpoint"):
            self._detail_checkpoint = DetailCheckpointService(
                root,
                scope=str(options.get("detail_checkpoint_scope") or "default"),
                filename=self.detail_checkpoint_filename,
                key_fn=self._detail_key,
                adapter_version="KYOBO_LIFE.detail.v1",
            )
        return self._detail_checkpoint

    @staticmethod
    def _detail_key(product: dict[str, Any]) -> str:
        """교보 상세를 식별하는 목록의 두 키를 정규화해 결합한다."""
        seq_value = product.get("dgtPdtAtrSeqtId")
        code_value = product.get("dgtPdtCd")
        seq = "" if seq_value is None else str(seq_value).strip()
        code = "" if code_value is None else str(code_value).strip()
        return f"{seq}|{code}"

    @classmethod
    def _require_detail_identifiers(cls, product: dict[str, Any]) -> tuple[str, str]:
        seq_value = product.get("dgtPdtAtrSeqtId")
        code_value = product.get("dgtPdtCd")
        seq = "" if seq_value is None else str(seq_value).strip()
        code = "" if code_value is None else str(code_value).strip()
        # 상세 API payload에는 상품 속성 순번만 사용된다. 실제 목록에는
        # dgtPdtCd가 비어 있지만 유효한 순번을 가진 구상품이 있으므로,
        # 상품코드를 필수로 취급하면 조회 가능한 상품까지 누락된다.
        if not seq:
            raise ValueError("상세 필수 식별자(dgtPdtAtrSeqtId) 누락")
        return seq, code

    def _fetch_products(self) -> list[dict]:
        raw_rows: list[dict] = []
        page = 1
        total_pages = 1
        while page <= min(total_pages, MAX_PAGES):
            payload = {
                "dgtPdtAtrDvCd": "M",
                "dgtPdtAtrLclCd": "",
                "dgtPdtAtrMclCd": "99",
                "dgtPdtAtrSmclCd": "99",
                "saleYn": "99",              # 99 = 판매중 + 판매중지 전체
                "dgtMseAddiPsYn": "",
                "searchTxt": "",
                "currentPage": page,
                "pagePerSize": PAGE_SIZE,
                "pageNumber": 10,
                "deviceDv": "pc",
            }
            response = json_post(self.client, LIST_URL, payload, referer=SEARCH_PAGE)
            if response.status_code == 403:
                raise AccessDeniedError(f"교보생명 목록 page={page} HTTP 403")
            if response.status_code != 200:
                raise RuntimeError(f"교보생명 목록 page={page} HTTP {response.status_code}")
            try:
                payload_body = response.json()
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"교보생명 목록 page={page} JSON 해석 실패") from exc
            if not isinstance(payload_body, dict):
                raise RuntimeError(f"교보생명 목록 page={page} 응답 envelope가 객체가 아닙니다")
            body = payload_body.get("body")
            if not isinstance(body, dict):
                raise RuntimeError(f"교보생명 목록 page={page} body가 누락되었거나 객체가 아닙니다")
            info = body.get("pageInfo")
            if not isinstance(info, dict) or "totPageCnt" not in info:
                raise RuntimeError(f"교보생명 목록 page={page} pageInfo 구조가 잘못되었습니다")
            try:
                total_pages = int(info["totPageCnt"])
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"교보생명 목록 page={page} totPageCnt가 숫자가 아닙니다") from exc
            if total_pages <= 0:
                raise RuntimeError(f"교보생명 목록 page={page} totPageCnt가 양수가 아닙니다")
            if total_pages > MAX_PAGES:
                raise RuntimeError(
                    f"교보생명 목록 page={page} totPageCnt={total_pages}가 안전 상한 {MAX_PAGES}를 초과합니다"
                )
            rows = body.get("list")
            if not isinstance(rows, list):
                raise RuntimeError(f"교보생명 목록 page={page} list가 누락되었거나 배열이 아닙니다")
            if any(not isinstance(row, dict) for row in rows):
                raise RuntimeError(f"교보생명 목록 page={page} list 항목이 객체가 아닙니다")
            raw_rows.extend(rows)
            if not rows or page >= total_pages:
                break
            page += 1
        out: list[dict] = []
        seen: set[str] = set()
        for row in raw_rows:
            key = self._product_seen_key(row)
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        self.stats["products_raw"] = len(raw_rows)
        self.stats["products_deduped"] = len(out)
        self.stats["products_duplicates"] = len(raw_rows) - len(out)
        self.stats["raw_rows"] = len(raw_rows)
        self.stats["dedup_rows"] = len(out)
        return out

    @staticmethod
    def _product_seen_key(product: dict[str, Any]) -> str:
        """목록 단계에서 상세 식별자 중복을 제거하는 안정 키."""
        seq_value = product.get("dgtPdtAtrSeqtId")
        code_value = product.get("dgtPdtCd")
        seq = "" if seq_value is None else str(seq_value).strip()
        code = "" if code_value is None else str(code_value).strip()
        if seq and code:
            return f"ids:{seq}|{code}"
        # 식별자가 모두 비어 있는 행은 누락 자체를 보존해야 이후 상세
        # 단계의 엄격한 실패 처리가 동작한다. 완전 동일한 raw row만 제거한다.
        try:
            signature = json.dumps(product, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        except (TypeError, ValueError):
            signature = repr(product)
        return "raw:" + signature

    def _fetch_versions(self, product: dict) -> list[ProductVersion]:
        seq, _code = self._require_detail_identifiers(product)
        response = json_post(self.client, DETAIL_URL, {"dgtPdtPdSeqtId": seq}, referer=SEARCH_PAGE)
        if response.status_code == 403:
            raise AccessDeniedError(f"교보생명 상세 seq={seq} HTTP 403")
        if response.status_code != 200:
            raise RuntimeError(f"상세 조회 HTTP {response.status_code}")
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - HTML/WAF 및 잘못된 JSON
            raise ValueError("상세 응답 JSON 해석 실패") from exc
        if not isinstance(payload, dict):
            raise ValueError("상세 응답 JSON body가 객체가 아닙니다")
        body = payload.get("body")
        if not isinstance(body, dict):
            raise ValueError("상세 응답 body가 객체가 아닙니다")
        periods = body.get("list")
        if not isinstance(periods, list):
            raise ValueError("상세 응답 body.list가 배열이 아닙니다")
        # list2 is optional: some products have no disclosed files at all.
        files = body.get("list2")
        if not isinstance(files, list):
            files = []

        category = " / ".join(
            x for x in (str(product.get("dgtPdtAtrMclCd") or ""), str(product.get("dgtPdtAtrSmclCd") or "")) if x
        )
        name = str(product.get("dgtPdtAtrNm") or "").strip()
        sale_yn = str(product.get("saleYn") or "")

        out: list[ProductVersion] = []
        for index, period in enumerate(periods):
            if not isinstance(period, dict):
                raise ValueError("상세 응답 body.list 항목이 객체가 아닙니다")
            sale_start = parse_date(str(period.get("saleStDt") or "")[:10])
            sale_end = parse_date(str(period.get("saleEdDt") or "")[:10])
            version = ProductVersion(
                company_code=self.code,
                company_name=self.name,
                storage_name=self.company.storage_name,
                product_name_raw=name,
                product_category=category,
                source_product_id=str(product.get("dgtPdtCd") or seq),
                sale_status="판매중" if (sale_yn == "Y" and sale_end is None) else "판매중지",
                sale_start_date=sale_start,
                sale_end_date=sale_end,
                source_page_url=SEARCH_PAGE,
                extra={"dgtPdtAtrSeqtId": seq},
            )
            if sale_start:
                version.version_key = f"{sale_start:%Y%m%d}_판매개시"
            file_row = files[index] if index < len(files) and isinstance(files[index], dict) else {}
            for field, label in DOC_FIELDS:
                file_name = str(file_row.get(field) or "").strip()
                if not file_name:
                    continue
                doc = self.make_document(
                    label=label,
                    url=DOWNLOAD_URL + quote(file_name),
                    filename=file_name.split("_", 1)[-1],
                )
                if doc is not None:
                    version.documents.append(doc)
            out.append(version)
        return out
