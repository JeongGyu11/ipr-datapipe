"""삼성생명 Adapter.

수집 방식: **HYBRID** — Playwright 로 목록을 얻고, 파일은 기존 HttpClient 로 내려받는다.
(docs/sites/SAMSUNG_LIFE.md)

왜 하이브리드인가
  - 상품 목록 API `POST /gw/api/product/disclosure/product/prdt/salesAllPrdtList` 의
    **요청 본문**이 Yettiesoft VestWeb 으로 암호화(`g=…&b=…`)되어 httpx 로 만들 수 없다.
    (평문/빈 본문 호출은 `code 9999 UNKNOWN ERROR` — 실측)
  - 반면 **응답은 평문 JSON** 이고, 문서 파일은 인증 없는 정적 경로로 제공된다.
  → 암호화 로직을 역산하지 않고, 사이트가 의도한 화면 동작(페이지 이동)을 브라우저로 수행하면서
    응답만 가로채고, 다운로드는 공통 HttpClient 로 처리한다.

응답 필드
    goodsCode / goodsName / fromdate / todate / lCode(판매중지·판매중)
    mCode>gCode>sCode(분류) / filename1~3 / totalRows / pageSize / pageNo

문서 경로 (실측 검증)
    filename2 -> docType 401 사업방법서
    filename3 -> docType 301 보험약관
    filename1 -> docType 201 상품요약서
    URL = https://pcms.samsunglife.com/uploadDir/doc/{YYYY}/{MMDD}/{goodsCode}/{docType}/{filename}.pdf
    ({YYYY}/{MMDD} 는 filename(epoch ms) 의 업로드 일자)
"""

from __future__ import annotations

import datetime
import json
import time
from datetime import date

from crawler.base_adapter import BaseInsurerAdapter
from crawler.http_client import AccessDeniedError
from models.product_version import ProductVersion
from utils.date_utils import parse_date

PAGE_URL = "https://www.samsunglife.com/individual/products/disclosure/sales/PDO-PRPRI010110M"
LIST_API = "/gw/api/product/disclosure/product/prdt/salesAllPrdtList"
FILE_BASE = "https://pcms.samsunglife.com/uploadDir/doc"

#: 응답 필드 -> (화면 표시명, docType)
DOC_FIELDS = [
    ("filename1", "상품요약서", "201"),
    ("filename2", "사업방법서", "401"),
    ("filename3", "보험약관", "301"),
]

MAX_PAGES = 800


def _file_url(goods_code: str, doc_type: str, file_name: str) -> str:
    stamp = datetime.datetime.fromtimestamp(int(file_name) / 1000)
    return f"{FILE_BASE}/{stamp:%Y}/{stamp:%m%d}/{goods_code}/{doc_type}/{file_name}.pdf"


class SamsungLifeAdapter(BaseInsurerAdapter):
    code = "SAMSUNG_LIFE"
    collection_method = "HYBRID - Playwright 로 목록 수집(요청 암호화) + HttpClient 로 파일 다운로드"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._captured: list[list[dict]] = []

    # ------------------------------------------------------------------
    def open(self) -> None:
        if self._page is not None:
            return
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.config.headless)
        self._context = self._browser.new_context(
            locale="ko-KR", user_agent=self.config.user_agent, ignore_https_errors=True
        )
        self._page = self._context.new_page()
        self._page.on("response", self._on_response)
        self._page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=90_000)
        self._page.wait_for_timeout(9_000)

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

    def _on_response(self, response) -> None:
        if LIST_API not in response.url:
            return
        try:
            payload = json.loads(response.text())
        except Exception:  # noqa: BLE001 - 목록 외 응답은 무시
            return
        rows = payload.get("response")
        if isinstance(rows, list) and rows and "goodsCode" in rows[0]:
            self._captured.append(rows)

    # ------------------------------------------------------------------
    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        self.open()
        if not self._captured:
            raise AccessDeniedError(
                "삼성생명 상품 목록 응답을 받지 못했습니다(화면 로딩 실패). 우회하지 않습니다."
            )

        total = int(self._captured[0][0].get("totalRows") or 0)
        page_size = int(self._captured[0][0].get("pageSize") or 10)
        pages = (total + page_size - 1) // page_size if page_size else 1
        self.log.info("[SAMSUNG_LIFE] 전체 %d건 / 페이지당 %d건 → %d페이지", total, page_size, pages)
        self.stats["total_rows"] = total

        limit = self.runtime_options.get("max_pages")
        if limit:
            pages = min(pages, int(limit))
            self.stats["coverage_capped"] = True
            self.stats["pages_limit"] = pages

        seen_pages = {int(self._captured[0][0].get("pageNo") or 1)}
        for page_no in range(2, min(pages, MAX_PAGES) + 1):
            if not self._goto_page(page_no):
                break
            seen_pages.add(page_no)
            if page_no % 25 == 0:
                self.log.info("[SAMSUNG_LIFE] 목록 진행 %d/%d 페이지", page_no, pages)

        rows: list[dict] = [row for chunk in self._captured for row in chunk]
        self.log.info("[SAMSUNG_LIFE] 수신 행 %d건(%d페이지)", len(rows), len(seen_pages))

        versions: list[ProductVersion] = []
        seen_keys: set[tuple] = set()
        for row in rows:
            version = self._to_version(row)
            if version is None:
                continue
            key = (version.product_name_raw, version.sale_start_date,
                   version.sale_end_date, version.source_product_id)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            versions.append(version)
        self.log.info("[SAMSUNG_LIFE] 상품 버전 %d건 수집", len(versions))
        return versions

    def _goto_page(self, page_no: int) -> bool:
        """화면의 페이지 이동을 그대로 수행한다(암호화는 사이트 스크립트가 처리)."""
        before = len(self._captured)
        time.sleep(self._interval())
        clicked = self._page.evaluate(
            """(no) => {
                const els = [...document.querySelectorAll('a,button')]
                    .filter(e => e.textContent.trim() === String(no));
                if (!els.length) return false;
                els[els.length - 1].click();
                return true;
            }""",
            page_no,
        )
        if not clicked:
            # 페이지 번호 버튼이 보이지 않으면 '다음' 으로 이동
            clicked = self._page.evaluate(
                """() => {
                    const el = [...document.querySelectorAll('a,button')]
                        .find(e => /다음|next/i.test(e.getAttribute('title') || e.textContent || ''));
                    if (!el) return false;
                    el.click();
                    return true;
                }"""
            )
        if not clicked:
            return False
        self._page.wait_for_timeout(2_000)
        return len(self._captured) > before

    # ------------------------------------------------------------------
    def _to_version(self, row: dict) -> ProductVersion | None:
        name = str(row.get("goodsName") or "").strip()
        goods_code = str(row.get("goodsCode") or "").strip()
        if not name or not goods_code:
            return None
        sale_start = parse_date(row.get("fromdate"))
        sale_end = parse_date(row.get("todate"))
        status = str(row.get("lCode") or "").strip() or "판매중"

        version = ProductVersion(
            company_code=self.code,
            company_name=self.name,
            storage_name=self.company.storage_name,
            product_name_raw=name,
            product_category=str(row.get("gubun") or "").strip(),
            source_product_id=goods_code,
            sale_status=status,
            sale_start_date=sale_start,
            sale_end_date=sale_end,
            source_page_url=PAGE_URL,
            extra={"status": row.get("status")},
        )
        if sale_start:
            version.version_key = f"{sale_start:%Y%m%d}_판매개시"

        for field, label, doc_type in DOC_FIELDS:
            file_name = str(row.get(field) or "").strip()
            if not file_name or not file_name.isdigit():
                continue
            try:
                url = _file_url(goods_code, doc_type, file_name)
            except (ValueError, OSError, OverflowError):
                continue
            doc = self.make_document(label=label, url=url, filename=f"{file_name}.pdf")
            if doc is not None:
                version.documents.append(doc)
        return version
