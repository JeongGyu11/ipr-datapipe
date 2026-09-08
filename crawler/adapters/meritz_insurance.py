"""메리츠화재 Adapter.

수집 방식: Playwright(헤드풀) + 페이지 내 API 호출 (SITE_ANALYSIS.md §3)

메리츠화재는 웹방화벽이 동작하여
  - headless 브라우저의 화면 진입이 차단되고
  - 외부 HTTP 클라이언트의 /hp/fileDownload.do 호출이 차단된다.
우회를 시도하지 않고, 실제 브라우저에서 사이트가 제공하는 동작을 그대로 수행한다.
차단이 계속되면 ACCESS_DENIED 로 기록한다.
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from crawler.base_adapter import BaseInsurerAdapter, FetchResult
from crawler.http_client import AccessDeniedError
from models.document import Document, DownloadStatus
from models.product_version import ProductVersion
from utils.date_utils import overlaps_month, parse_date

PAGE_URL = "https://www.meritzfire.com/disclosure/product-announcement/product-list.do?vMode=PC"

#: 페이지의 AngularJS bc 서비스를 그대로 호출한다.
JS_CALL = """async ([service, body]) => {
    const inj = angular.element(document.querySelector('[data-ng-view]')).injector();
    const bc = inj.get('bc');
    const res = await bc[service](body);
    return (res && res.body) ? res.body : {};
}"""

#: 페이지의 fileUtil.download() 를 그대로 호출한다(사이트의 정상 다운로드 동작).
JS_DOWNLOAD = """([token, orgFileName]) => {
    const inj = angular.element(document.querySelector('[data-ng-view]')).injector();
    inj.get('fileUtil').download('/hp/fileDownload.do',
        {path: token, id: token, orgFileName: orgFileName});
}"""

#: salPdList 필드 -> 화면 표시명 (salPdLst.js 의 pdfDown 분기로 확인)
DOC_FIELDS = [
    ("file1", "약관"),
    ("file2", "사업방법서"),
    ("file3", "상품요약서"),
    ("file4", "상품설명서"),   # 기본 제외 대상
]


class MeritzInsuranceAdapter(BaseInsurerAdapter):
    code = "MERITZ"
    collection_method = "3순위 - Playwright(헤드풀) + 페이지 내 bc/fileUtil 호출 (웹방화벽)"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._tempdir: TemporaryDirectory | None = None

    # ------------------------------------------------------------------
    # 브라우저 수명주기 (보험사 단위로 1회만 기동)
    # ------------------------------------------------------------------
    def open(self) -> None:
        if self._page is not None:
            return
        from playwright.sync_api import sync_playwright

        if self.config.headless:
            self.log.warning(
                "[MERITZ] 웹방화벽이 headless 브라우저를 차단하므로 headless=False 로 실행합니다."
            )
        self._tempdir = TemporaryDirectory(prefix="meritz_dl_")
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = self._browser.new_context(
            accept_downloads=True,
            locale="ko-KR",
            user_agent=self.config.user_agent,
        )
        self._page = self._context.new_page()
        self._page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=90_000)
        self._page.wait_for_timeout(7_000)
        self._assert_not_blocked()

    def close(self) -> None:
        super().close()
        for closer in (
            getattr(self._context, "close", None),
            getattr(self._browser, "close", None),
            getattr(self._playwright, "stop", None),
        ):
            if closer is not None:
                try:
                    closer()
                except Exception:  # noqa: BLE001 - 정리 실패는 무시
                    pass
        self._page = self._context = self._browser = self._playwright = None
        if self._tempdir is not None:
            self._tempdir.cleanup()
            self._tempdir = None

    def _assert_not_blocked(self) -> None:
        body = (self._page.inner_text("body") or "").lower()
        if "firewall" in body or "blocked" in body:
            raise AccessDeniedError("메리츠화재 웹방화벽이 접근을 차단했습니다(우회하지 않음).")

    def _throttle(self) -> None:
        time.sleep(self._interval())

    def _call(self, service: str, body: dict) -> dict:
        self._throttle()
        result = self._page.evaluate(JS_CALL, [service, body])
        if not isinstance(result, dict):
            raise RuntimeError(f"메리츠 {service} 응답 body가 객체가 아닙니다")
        return result

    @staticmethod
    def _required_list(payload: dict, key: str, service: str) -> list[dict]:
        """API envelope의 필수 배열을 엄격히 검증한다.

        ``[]``는 정상적인 빈 조회 결과지만, 키 누락/잘못된 타입은 장애를
        빈 성공으로 기록하지 않도록 즉시 실패시킨다.
        """
        if key not in payload or not isinstance(payload[key], list):
            raise RuntimeError(f"메리츠 {service} 응답 {key}가 누락되었거나 배열이 아닙니다")
        rows = payload[key]
        if any(not isinstance(row, dict) for row in rows):
            raise RuntimeError(f"메리츠 {service} 응답 {key} 항목이 객체가 아닙니다")
        return rows

    # ------------------------------------------------------------------
    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        self.stats["status_coverage_complete"] = False
        self.open()
        self.stats.update(
            api_rows=0,
            raw_rows=0,
            materialized_rows=0,
            filtered_rows=0,
            unknown_dates=0,
        )
        versions: list[ProductVersion] = []
        categories_seen = 0

        for notf_yn, sale_status in (("Y", "판매중"), ("N", "판매중지")):
            root = self._call("retrievePdList", {"notfYn": notf_yn, "srtSq": "1"})
            categories = self._required_list(root, "pdList", "retrievePdList")
            self.log.info("[MERITZ] %s 상품종류 %d개", sale_status, len(categories))

            #: cmCommCd -> 상품종류명
            division_names: dict[str, str] = {}
            for category in categories:
                srt_sq = str(category.get("srtSq", ""))
                detail = self._call("retrievePdList", {"notfYn": notf_yn, "srtSq": srt_sq})
                for item in self._required_list(detail, "pdDtlList", "retrievePdList"):
                    if str(item.get("srtSq", "")) != srt_sq:
                        continue
                    code = str(item.get("cmCommCd") or "")
                    if code:
                        division_names.setdefault(code, str(category.get("cdNm") or ""))
            categories_seen += len(division_names)

            for division_code, category_name in division_names.items():
                body = {"cmPdDivCd": division_code, "notfYn": notf_yn, "bcType": "SALPD_LST"}
                rows = self._required_list(
                    self._call("retrieveSalPdList", body), "salPdList", "retrieveSalPdList"
                )
                self.stats["api_rows"] = int(self.stats["api_rows"]) + len(rows)
                self.stats["raw_rows"] = int(self.stats["raw_rows"]) + len(rows)
                self.log.info(
                    "[MERITZ] %s / %s (%s) 상품버전 %d건",
                    sale_status, category_name, division_code, len(rows),
                )
                for row in rows:
                    # 목록 행에서 날짜만 먼저 읽어 범위 밖 상품은 브라우저
                    # 세션/문서 객체를 만들지 않는다. ``overlap`` 모드에서는
                    # 과거에 시작했지만 대상 기간에 판매 중인 버전도 보존한다.
                    sale_start = parse_date(row.get("bgnDt"))
                    sale_end = parse_date(row.get("putupEdDdTm"))
                    disclosure = parse_date(row.get("putupStDdTm"))
                    active_match = (
                        bool(self._active_status_rows)
                        and self.matches_active_status_reference(
                            source_product_id=row.get("ntbdDtlSeq"),
                            product_name=row.get("ttlNm"),
                            sale_start_date=sale_start,
                            target_date=disclosure,
                        )
                    )
                    if not (
                        self._is_candidate(
                            sale_start, sale_end, disclosure, start_date, end_date
                        )
                        or active_match
                    ):
                        self.stats["filtered_rows"] = int(self.stats.get("filtered_rows", 0)) + 1
                        continue
                    version = self._to_version(row, category_name, sale_status)
                    versions.append(version)

        self.stats["divisions"] = categories_seen
        self.stats["materialized_rows"] = len(versions)
        self.stats["unknown_dates"] = sum(1 for v in versions if v.target_date is None)
        self.stats["status_coverage_complete"] = True
        return versions

    def _is_candidate(
        self,
        sale_start: date | None,
        sale_end: date | None,
        disclosure: date | None,
        start_date: date | None,
        end_date: date | None,
    ) -> bool:
        """날짜 메타데이터만으로 materialize 여부를 판단한다.

        날짜를 전혀 모르는 행은 자동으로 버리면 안 된다. 이후 공통
        selector가 MANUAL_REVIEW_REQUIRED 로 기록할 수 있도록 항상 남긴다.
        """
        if start_date is None or end_date is None:
            return True
        mode = str(getattr(self.config, "date_selection_mode", "new_or_revised") or "new_or_revised")
        # 기준 날짜가 전혀 없으면 판매종료일만으로도 버리지 않는다. 공통
        # selector가 수동검토/종료 확정을 맡는다.
        if sale_start is None and disclosure is None:
            return True
        if mode == "overlap":
            return overlaps_month(sale_start, sale_end, start_date, end_date)
        if mode != "new_or_revised":
            raise ValueError(f"알 수 없는 date_selection.mode: {mode!r}")
        target = sale_start or disclosure
        return target is None or start_date <= target <= end_date

    # ------------------------------------------------------------------
    def _to_version(self, row: dict, category: str, sale_status: str) -> ProductVersion:
        start = parse_date(row.get("bgnDt"))
        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=str(row.get("ttlNm") or "").strip(),
            product_category=category,
            source_product_id=str(row.get("ntbdDtlSeq") or ""),
            sale_status=sale_status,
            sale_start_date=start,
            sale_end_date=parse_date(row.get("putupEdDdTm")),
            disclosure_date=parse_date(row.get("putupStDdTm")),
            source_page_url=PAGE_URL,
            version_key=f"{start:%Y%m%d}_판매개시" if start else "",
        )
        for field_name, label in DOC_FIELDS:
            path = str(row.get(field_name) or "").strip()
            token = row.get(f"{field_name}#[E]")
            if not path or not token:
                continue
            document = self.make_document(
                label=label,
                url="",  # 실제 URL 은 세션 토큰 기반이라 고정 URL 이 없다
                filename=path.rsplit("/", 1)[-1],
                token=token,
                server_path=path,
                org_file_name=f"{version.product_name_raw}{label}.pdf",
            )
            if document is not None:
                # 고정 다운로드 URL 이 없으므로 엔드포인트 + 사이트가 알려준 서버 경로를 남긴다.
                # (실제 요청에는 세션마다 달라지는 암호화 토큰이 쓰인다)
                document.document_url = (
                    f"https://www.meritzfire.com/hp/fileDownload.do?serverPath={path}"
                )
                version.documents.append(document)
        return version

    # ------------------------------------------------------------------
    def fetch_document(self, document: Document) -> FetchResult:
        """페이지 안에서 사이트의 다운로드 함수를 호출하고 파일을 수신한다."""
        token = document.download_hint.get("token")
        if not token:
            return FetchResult(False, DownloadStatus.NO_DOCUMENT_LINK, reason="다운로드 토큰 없음")

        self.open()
        org_name = document.download_hint.get("org_file_name") or document.original_filename
        try:
            self._throttle()
            with self._page.expect_download(timeout=180_000) as download_info:
                self._page.evaluate(JS_DOWNLOAD, [token, org_name])
            download = download_info.value
        except Exception as exc:  # noqa: BLE001 - Playwright 예외 전부 기록
            body = ""
            try:
                body = (self._page.inner_text("body") or "").lower()
            except Exception:  # noqa: BLE001
                pass
            if "firewall" in body or "blocked" in body:
                return FetchResult(False, DownloadStatus.ACCESS_DENIED, reason="웹방화벽 차단")
            return FetchResult(False, DownloadStatus.DOWNLOAD_FAILED, reason=f"{type(exc).__name__}: {exc}")

        target = Path(self._tempdir.name) / f"dl_{abs(hash(token))}"
        try:
            download.save_as(target)
            data = target.read_bytes()
        except Exception as exc:  # noqa: BLE001
            failure = download.failure()
            return FetchResult(
                False,
                DownloadStatus.DOWNLOAD_FAILED,
                reason=f"파일 수신 실패: {failure or exc}",
            )
        finally:
            target.unlink(missing_ok=True)

        return FetchResult(
            ok=True,
            status=DownloadStatus.SUCCESS,
            content=data,
            content_type="application/pdf",
            original_filename=download.suggested_filename or org_name,
            http_status=200,
            final_url=document.document_url,
        )
