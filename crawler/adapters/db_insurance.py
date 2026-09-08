"""DB손해보험 Adapter.

수집 방식: 공시실 화면이 호출하는 JSON API 재현 (SITE_ANALYSIS.md §1)
  - 기간 검색: POST /insuPcPbanFindProductStep5_AX.do
  - 판매종료일 보강: POST /insuPcPbanFindProductStep4_AX.do
  - 문서: GET /cYakgwanDown.do?FilePath=InsProduct/{파일명}
"""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import quote

from crawler.base_adapter import BaseInsurerAdapter
from crawler.http_client import AccessDeniedError
from models.product_version import ProductVersion
from utils.date_utils import parse_date

BASE = "https://www.idbins.com"
STEP4 = "/insuPcPbanFindProductStep4_AX.do"
STEP5 = "/insuPcPbanFindProductStep5_AX.do"
DOWNLOAD = "/cYakgwanDown.do?FilePath=InsProduct/"

#: 응답 필드 -> 화면에 표시되는 문서명
DOC_FIELDS = [
    ("INPL_FINM", "보험약관"),
    ("BIZ_MDDC_FINM", "사업방법서"),
    ("CNSL_SMAR_FINM", "상품요약서"),
    ("PDC_EXPP_FINM", "상품설명서"),   # 기본 제외 대상 (classifier 가 걸러냄)
]


class DBInsuranceAdapter(BaseInsurerAdapter):
    code = "DB"
    collection_method = "1순위 - 공시실 화면 JSON API 재현 (기간검색 Step5)"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        # Leave coverage incomplete until Step5 and all required targeted
        # Step4 refreshes have returned successfully.
        self.stats["status_coverage_complete"] = False
        limit_value = self.runtime_options.get("max_products")
        limit = None
        if limit_value is not None and str(limit_value).strip():
            if isinstance(limit_value, bool):
                raise ValueError("DB max_products는 1 이상의 정수여야 합니다")
            if isinstance(limit_value, int):
                limit = limit_value
            elif isinstance(limit_value, str) and limit_value.strip().isdecimal():
                limit = int(limit_value.strip())
            else:
                raise ValueError("DB max_products는 1 이상의 정수여야 합니다")
            if limit <= 0:
                raise ValueError("DB max_products는 1 이상의 정수여야 합니다")
        rows = self._search(start_date, end_date)
        self.log.info("[DB] 기간검색 결과 %d건 (%s ~ %s)", len(rows), start_date, end_date)
        self.stats.update(
            api_rows=len(rows),
            raw_rows=len(rows),
            materialized_rows=0,
            filtered_rows=0,
            coverage_capped=False,
            products_total=len(rows),
            products_skipped=0,
            step4_attempted=0,
            step4_succeeded=0,
            step4_failed=0,
            step4_deferred=0,
        )
        if limit is not None:
            rows = rows[:limit]
            self.stats["products_skipped"] = max(0, int(self.stats["products_total"]) - len(rows))
            self.stats["coverage_capped"] = self.stats["products_skipped"] > 0
            if self.stats["coverage_capped"]:
                self.log.warning(
                    "[DB] max_products=%d 적용: 기간검색 %d건 중 %d건만 상세 조회합니다 "
                    "(coverage_capped).",
                    limit,
                    self.stats["products_total"],
                    len(rows),
                )
        # Adapter 인스턴스가 테스트나 장기 프로세스에서 재사용되더라도
        # 이전 수집 범위의 상세 응답을 새 범위에 섞지 않는다.
        self._step4_cache = {}
        # Status refresh uses the same Step4 cache as the period pass.  This
        # keeps a normal row and a targeted manifest row from issuing duplicate
        # requests for the same (SQNO, sale flag) pair.
        mode = str(getattr(self.config, "date_selection_mode", "new_or_revised") or "new_or_revised")
        if mode not in ("new_or_revised", "overlap"):
            raise ValueError(f"알 수 없는 date_selection.mode: {mode!r}")

        versions: list[ProductVersion] = []
        for row in rows:
            sale_start = parse_date(row.get("SALE_BEGIN_DAY"))
            # Step5의 메타데이터로 먼저 후보를 줄인다. 시작일을 알 수 없는
            # 행은 수동검토를 위해 버리지 않고 Step4를 시도한다.
            if not self._step4_candidate(sale_start, start_date, end_date, mode):
                self.stats["step4_deferred"] += 1
                self.stats["filtered_rows"] += 1
                continue

            version = self._to_version(row)
            if not version.source_product_id:
                self.stats["step4_deferred"] += 1
                self.log.warning("[DB] SQNO 미상 행은 Step4를 조회할 수 없어 수동검토 대상으로 보존합니다.")
            else:
                self._fill_sale_end_date(version, row)

            # Step4에서 시작일이 보강/정정될 수 있으므로 최종 판정은
            # 상세 응답 반영 후 수행한다. 날짜 미상은 항상 보존한다.
            if not self._selected_after_detail(version, start_date, end_date, mode):
                self.stats["filtered_rows"] += 1
                continue
            versions.append(version)
            self.stats["materialized_rows"] += 1

        # Step5 is intentionally period-filtered, so an old ACTIVE manifest
        # version may not be present in ``rows`` at all.  Revalidate those
        # identities with the same Step4 cache and append a lightweight
        # observation-compatible version for reconciliation.
        active_rows = self.active_status_rows
        coverage_capped = bool(self.stats.get("coverage_capped"))
        if active_rows:
            refreshed, complete = self._refresh_active_status_rows(active_rows, versions)
            versions.extend(refreshed)
            self.stats["status_coverage_complete"] = (
                not coverage_capped
                and bool(complete)
                and int(self.stats.get("step4_failed", 0)) == 0
            )
        else:
            self.stats["status_coverage_complete"] = (
                not coverage_capped and int(self.stats.get("step4_failed", 0)) == 0
            )
        return versions

    def _refresh_active_status_rows(
        self, rows: list[dict], existing: list[ProductVersion] | None = None
    ) -> tuple[list[ProductVersion], bool]:
        """Step4-only refresh for configured old ACTIVE manifest rows.

        Step4 failures are deliberately represented as an unchanged ACTIVE
        observation (never as an inferred end date).  Access control errors
        remain fatal through :meth:`_fill_sale_end_date`/``_post_json``.
        """
        out: list[ProductVersion] = []
        complete = True
        seen: set[tuple[str, str]] = set()
        for row in rows:
            sqno = str(row.get("source_product_id") or row.get("SQNO") or "").strip()
            if not sqno:
                complete = False
                continue
            # Configured rows are ACTIVE by contract.  Keep the explicit flag
            # when a caller supplied one, while normalising common spellings.
            raw_status = str(row.get("sale_status") or row.get("normalized_sale_status") or "ACTIVE").upper()
            status_flag = "0" if raw_status in {"판매중지", "ENDED", "END", "0", "FALSE"} else "1"
            key = (sqno, status_flag)
            # Keep materialising each manifest version (the same SQNO may
            # legitimately have multiple sale-start revisions), while the
            # Step4 cache below still guarantees one request per pair.
            seen.add(key)
            # A period row may already have gone through the exact Step4
            # request above.  Reuse that materialized version instead of
            # emitting a duplicate download candidate.
            if existing and any(
                str(v.source_product_id or "").strip() == sqno
                and (
                    not str(row.get("sale_start_date") or row.get("target_date") or "").strip()
                    or not str(v.sale_start_date or "").strip()
                    or self._status_date_key(v.sale_start_date)
                    == self._status_date_key(row.get("sale_start_date") or row.get("target_date"))
                )
                for v in existing
            ):
                continue
            old_start = parse_date(row.get("sale_start_date") or row.get("target_date"))
            version = ProductVersion(
                company_code=self.code,
                company_name=self.name,
                storage_name=self.company.storage_name,
                product_name_raw=str(
                    row.get("product_name_raw")
                    or row.get("product_name")
                    or row.get("product_name_normalized")
                    or ""
                ).strip(),
                product_category=str(row.get("product_category") or "").strip(),
                source_product_id=sqno,
                version_key=(f"{old_start:%Y%m%d}_판매개시" if old_start else str(row.get("version_key") or "")),
                sale_status="판매중",
                sale_start_date=old_start,
                source_page_url=str(row.get("source_page_url") or self.base_url),
            )
            detail_before = int(self.stats.get("step4_failed", 0))
            self._fill_sale_end_date(version, {"SQNO": sqno, "ARC_PDC_SL_YN": status_flag})
            cache_detail = getattr(self, "_step4_cache", {}).get(key)
            if int(self.stats.get("step4_failed", 0)) != detail_before or cache_detail is None:
                # Missing/failed Step4 is not evidence of an ended product.
                complete = False
                version.sale_status = "판매중"
                version.sale_end_date = None
            elif version.sale_end_date is not None:
                version.sale_status = "판매중지"
            # This synthetic row exists only for status reconciliation; never
            # turn Step4's document hints into a second download plan.
            version.documents = []
            # Preserve manifest identity even when a detail payload carries a
            # corrected/alternate start date.
            version.sale_start_date = old_start
            if old_start:
                version.version_key = f"{old_start:%Y%m%d}_판매개시"
            out.append(version)
        self.stats["active_status_refreshed"] = len(out)
        return out, complete

    @staticmethod
    def _step4_candidate(
        sale_start: date | None,
        start_date: date,
        end_date: date,
        mode: str,
    ) -> bool:
        """Step5 행이 Step4 상세조회 후보인지 판단한다."""
        if sale_start is None:
            return True
        if mode == "overlap":
            # 시작일이 대상기간 종료일보다 뒤면 겹칠 수 없으므로 지연한다.
            return sale_start <= end_date
        return start_date <= sale_start <= end_date

    @staticmethod
    def _selected_after_detail(
        version: ProductVersion,
        start_date: date,
        end_date: date,
        mode: str,
    ) -> bool:
        sale_start = version.sale_start_date
        sale_end = version.sale_end_date
        # 시작일을 끝내 알 수 없는 행은 selector가 수동검토로 다루도록 보존한다.
        if sale_start is None:
            return True
        if mode == "new_or_revised":
            return start_date <= sale_start <= end_date
        if sale_start > end_date:
            return False
        return sale_end is None or sale_end >= start_date

    # ------------------------------------------------------------------
    def _search(self, start_date: date, end_date: date) -> list[dict]:
        payload = {
            "searchCheck": "1",                    # 판매기간 검색
            "keyword": "",                         # 서버는 빈 검색어를 전체로 처리 (SITE_ANALYSIS.md §1.1)
            "beginDate": f"{start_date:%Y%m%d}",
            "endDate": f"{end_date:%Y%m%d}",
        }
        response = self._post_json(STEP5, payload)
        if not isinstance(response, dict):
            raise RuntimeError("DB Step5 응답 envelope가 객체가 아닙니다")
        rows = response.get("result")
        if not isinstance(rows, list):
            raise RuntimeError("DB Step5 응답 result가 배열이 아니거나 누락되었습니다")
        return rows

    def _post_json(self, path: str, payload: dict) -> dict:
        """DB손보 AJAX 는 application/json 만 허용한다 (form 전송 시 HTTP 415)."""
        response = self.client.post(
            BASE + path,
            content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=UTF-8",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        if response.status_code == 403:
            raise AccessDeniedError(f"DB {path} HTTP 403")
        if response.status_code != 200:
            raise RuntimeError(f"DB {path} HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            raise RuntimeError(f"DB {path} 응답 JSON 해석 실패") from None
        if not isinstance(payload, dict):
            raise RuntimeError(f"DB {path} 응답 JSON envelope가 객체가 아닙니다")
        return payload

    # ------------------------------------------------------------------
    def _to_version(self, row: dict) -> ProductVersion:
        sale_start = parse_date(row.get("SALE_BEGIN_DAY"))
        on_sale = str(row.get("ARC_PDC_SL_YN", "")) == "1"
        sqno = str(row.get("SQNO") or "").strip()

        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=str(row.get("PDC_NM", "")).strip(),
            product_category=str(row.get("ARC_KND_LGCG_NM", "")).strip(),
            source_product_id=sqno,
            sale_status="판매중" if on_sale else "판매중지",
            sale_start_date=sale_start,
            source_page_url=self.base_url,
        )
        if sale_start:
            version.version_key = f"{sale_start:%Y%m%d}_판매개시"

        for field_name, label in DOC_FIELDS:
            filename = str(row.get(field_name) or "").strip()
            if not filename:
                continue
            document = self.make_document(
                label=label,
                url=BASE + DOWNLOAD + quote(filename),
                filename=filename,
            )
            if document is not None:
                version.documents.append(document)
        return version

    def _fill_sale_end_date(self, version: ProductVersion, row: dict) -> None:
        """Step4 로 판매 시작/종료일을 보강한다(실패해도 수집은 계속)."""
        sqno = version.source_product_id
        if not sqno:
            return
        status_flag = "1" if version.sale_status == "판매중" else "0"
        cache = getattr(self, "_step4_cache", None)
        if cache is None:
            cache = self._step4_cache = {}
        # 동일 SQNO라도 판매중/판매중지 상태가 payload에 포함되므로
        # 상태 플래그까지 키에 포함한다.
        cache_key = (sqno, status_flag)
        if cache_key in cache:
            detail = cache[cache_key]
        else:
            self.stats["step4_attempted"] = int(self.stats.get("step4_attempted", 0)) + 1
            payload = {"sqno": sqno, "arc_pdc_sl_yn": status_flag}
            try:
                data = self._post_json(STEP4, payload)
                results = data.get("result")
                if not isinstance(results, list):
                    raise RuntimeError("DB Step4 응답 result가 배열이 아니거나 누락되었습니다")
                if results and not isinstance(results[0], dict):
                    raise RuntimeError("DB Step4 응답 result 항목이 객체가 아닙니다")
                detail = results[0] if results and isinstance(results[0], dict) else None
            except AccessDeniedError:
                # 403은 상품별 보강 실패가 아니라 회사 접근 통제이므로
                # 진행중(ongoing)으로 위장하지 않고 즉시 상위로 전파한다.
                raise
            except Exception as exc:  # noqa: BLE001 - 상세 실패는 누락 방지를 위해 ongoing 처리
                detail = None
                self.log.warning("[DB] SQNO %s Step4 조회 실패: %s", sqno, exc)
            cache[cache_key] = detail
            if detail is None:
                self.stats["step4_failed"] = int(self.stats.get("step4_failed", 0)) + 1
                self.log.warning("[DB] SQNO %s Step4 상세가 없어 판매종료일을 확인하지 못했습니다.", sqno)
            else:
                self.stats["step4_succeeded"] = int(self.stats.get("step4_succeeded", 0)) + 1

        if detail is None:
            # Step4 실패/빈 응답은 종료일 미상(ongoing)으로 남긴다.
            return
        version.sale_start_date = parse_date(detail.get("SL_STR_DT")) or version.sale_start_date
        version.sale_end_date = parse_date(detail.get("SL_FIN_DT"))
        self._merge_detail_documents(version, detail)
        if version.sale_start_date:
            version.version_key = f"{version.sale_start_date:%Y%m%d}_판매개시"
        if version.sale_end_date is None:
            self.log.warning("[DB] SQNO %s Step4 종료일 미상; 진행중으로 포함합니다.", sqno)

    def _merge_detail_documents(self, version: ProductVersion, detail: dict) -> None:
        """Step4에만 있는 문서도 보강하되 Step5 링크/순서를 보존한다."""
        existing = {doc.original_filename for doc in version.documents}
        for field_name, label in DOC_FIELDS:
            filename = str(detail.get(field_name) or "").strip()
            if not filename or filename in existing:
                continue
            document = self.make_document(
                label=label,
                url=BASE + DOWNLOAD + quote(filename),
                filename=filename,
            )
            if document is not None:
                version.documents.append(document)
                existing.add(filename)
