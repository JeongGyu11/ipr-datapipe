"""롯데손해보험 Adapter.

수집 방식: 공시실 화면 '검색형' 폼 POST 재현 (SITE_ANALYSIS.md §2)

    POST /CChannelSvl   (EUC-KR 폼)
        ops_tc = dfi.c.d.g.cmd.Cdg079Cmd
        rtnUri = /web/C/D/H/cdh190_result.jsp
        task   = searchKey
        srcPrdNm = <검색어>

응답 1회에 판매상품 표(searchviewissale)와 판매종료상품 표(searchviewisnotsale)가 함께 오며,
각 행에 상품군·상품명·판매기간·약관·사업방법서·상품요약서 링크가 모두 들어 있다.

'분류형' 4단계 드릴다운(gostep2~gostep4)도 동작하지만 상품 1건마다 요청이 필요해
전체 순회에 수 시간이 걸리므로, 동일한 데이터를 1회 요청으로 받을 수 있는 검색형을 사용한다.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote

from bs4 import BeautifulSoup

from crawler.base_adapter import BaseInsurerAdapter
from crawler.http_client import AccessDeniedError
from models.product_version import ProductVersion
from utils.date_utils import parse_date

BASE = "https://www.lotteins.co.kr"
SERVLET = f"{BASE}/CChannelSvl"
OPS_TC = "dfi.c.d.g.cmd.Cdg079Cmd"
RTN_URI = "/web/C/D/H/cdh190_result.jsp"

_INNER_HTML = re.compile(
    r'getElementById\(\s*"(?P<view>[A-Za-z0-9_]+)"\s*\)\.innerHTML\s*=\s*"(?P<html>.*?)"\s*;',
    re.S,
)
_PERIOD = re.compile(r"(\d{4}[.\-/]\d{2}[.\-/]\d{2})\s*~\s*(\d{4}[.\-/]\d{2}[.\-/]\d{2}|현재)?")

#: 응답의 view id -> 판매상태
VIEWS = {
    "searchviewissale": "판매중",
    "searchviewisnotsale": "판매중지",
}


class LotteInsuranceAdapter(BaseInsurerAdapter):
    code = "LOTTE"
    collection_method = "1순위 - 공시실 화면 검색형 폼 POST 재현 (searchKey 1회 조회)"

    def collect_product_versions(self, start_date: date, end_date: date) -> list[ProductVersion]:
        # LOTTE 응답은 판매중/판매중지 두 표를 한 번에 전량 반환한다.
        # 상태 갱신을 요청한 경우에도 별도 조회가 필요하지 않으며, 실패한
        # 수집이 이전 성공 상태를 재사용하지 않도록 먼저 미완료로 둔다.
        self.stats["status_coverage_complete"] = False
        html = self._search("")
        if not html or not html.strip():
            raise RuntimeError("롯데손해보험 검색 응답이 비어 있습니다")
        if not any(
            match.group("view") in VIEWS
            for match in _INNER_HTML.finditer(html)
        ):
            raise RuntimeError("롯데손해보험 검색 응답에 알려진 view assignment가 없습니다")

        versions: list[ProductVersion] = []
        total_rows = 0
        for view_id, sale_status in VIEWS.items():
            fragment = self._extract_view(html, view_id)
            if not fragment:
                continue
            rows = self._parse_rows(fragment, sale_status)
            total_rows += len(rows)
            self.log.info("[LOTTE] %s 상품버전 %d건", sale_status, len(rows))
            versions.extend(rows)

        self.stats["api_rows"] = total_rows
        self.stats["status_coverage_complete"] = True
        return versions

    # ------------------------------------------------------------------
    def _search(self, keyword: str) -> str:
        """검색형 조회. 검색어가 비어 있으면 전체 상품이 반환된다.

        폼이 EUC-KR 이므로 한글 검색어는 반드시 EUC-KR 로 인코딩해야 한다
        (UTF-8 로 보내면 결과가 0건으로 나온다 - 실측 확인).
        """
        fields = [
            ("ops_tc", OPS_TC),
            ("rtnUri", RTN_URI),
            ("task", "searchKey"),
            ("lcode", ""),
            ("mcode", ""),
            ("scode", ""),
            ("startdate", ""),
            ("issale", "Y"),
            ("srcPrdNm", keyword),
        ]
        body = "&".join(f"{k}={quote(v, encoding='euc-kr')}" for k, v in fields)
        response = self.client.post(
            SERVLET,
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=max(self.config.timeout, 120),
        )
        if response.status_code == 403:
            raise AccessDeniedError("롯데손해보험 검색 HTTP 403")
        if response.status_code != 200:
            raise RuntimeError(f"롯데손해보험 검색 HTTP {response.status_code}")
        return response.text

    @staticmethod
    def _extract_view(html: str, view_id: str) -> str:
        """응답 JS 안에서 특정 view 에 주입되는 HTML 조각을 꺼낸다."""
        best = ""
        for match in _INNER_HTML.finditer(html or ""):
            if match.group("view") != view_id:
                continue
            fragment = (
                match.group("html")
                .replace('\\"', '"')
                .replace("\\'", "'")
                .replace("\\/", "/")
            )
            if len(fragment) > len(best):
                best = fragment
        return best

    # ------------------------------------------------------------------
    def _parse_rows(self, fragment: str, sale_status: str) -> list[ProductVersion]:
        soup = BeautifulSoup(fragment, "lxml")
        versions: list[ProductVersion] = []
        for tr in soup.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 3:
                continue   # 헤더 행(th) 또는 '검색된 상품이 없습니다' 행

            category = cells[0].get_text(" ", strip=True)
            product_name = cells[1].get_text(" ", strip=True)
            period_text = cells[2].get_text(" ", strip=True)
            if not product_name:
                continue

            start = end = None
            match = _PERIOD.search(period_text)
            if match:
                start = parse_date(match.group(1))
                end = parse_date(match.group(2)) if match.group(2) else None

            version = ProductVersion(
                company_code=self.code,
                company_name=self.name,
                storage_name=self.company.storage_name,
                product_name_raw=product_name,
                product_category=category,
                sale_status=sale_status,
                sale_start_date=start,
                sale_end_date=end,
                source_page_url=self.base_url,
                version_key=f"{start:%Y%m%d}_판매개시" if start else "",
            )

            for cell in cells[3:]:
                anchor = cell.find("a", href=True)
                if anchor is None:
                    continue
                image = anchor.find("img")
                label = (image.get("alt") if image else "") or anchor.get("title", "")
                label = label.replace("새창열림_", "").replace("PDF보기", "").strip()
                href = anchor["href"].strip().strip("'\"")
                if not href or href.startswith("javascript"):
                    continue
                url = href if href.startswith("http") else BASE + href
                filename = href.rsplit("/", 1)[-1]
                document = self.make_document(label=label, url=url, filename=filename)
                if document is not None:
                    version.documents.append(document)

            # 상품 식별자가 응답에 없으므로 약관 파일명을 보조 식별자로 사용한다.
            if not version.source_product_id and version.documents:
                version.source_product_id = version.documents[0].original_filename
            versions.append(version)
        return versions
