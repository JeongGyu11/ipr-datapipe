"""신규 Adapter 공통 유틸(crawler/adapters/common.py) 테스트.

여기서 검증하는 케이스는 전부 실제 사이트 HTML/응답에서 가져온 형태입니다.
"""

from datetime import date

import pytest

from crawler.adapters.common import (
    absolute,
    clean,
    decode_body,
    js_call_args,
    parse_period,
    soup,
    table_rows,
)


# ---------------------------------------------------------------------------
# parse_period — 사이트별 판매기간 표기
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        # 메트라이프: 판매중 / 판매종료
        ("2026.07.01 ~ ", (date(2026, 7, 1), None)),
        ("2026.04.01 ~ 2026.06.30", (date(2026, 4, 1), date(2026, 6, 30))),
        # 흥국화재 판매중지 화면
        ("2026-05-06 ~ 2026-06-30", (date(2026, 5, 6), date(2026, 6, 30))),
        # 흥국화재 판매 화면(단일 날짜)
        ("2026-07-01", (date(2026, 7, 1), None)),
        # IBK연금보험
        ("2026-01-01 ~ 현재", (date(2026, 1, 1), None)),
        # KB라이프
        ("2026/07/01 ~ ", (date(2026, 7, 1), None)),
        ("2026/01/01 ~ 2026/06/30", (date(2026, 1, 1), date(2026, 6, 30))),
        # 하나생명
        ("2026.04.01 -", (date(2026, 4, 1), None)),
        # 값 없음
        ("", (None, None)),
        ("판매기간", (None, None)),
    ],
)
def test_parse_period(text, expected):
    assert parse_period(text) == expected


def test_parse_period_ignores_open_ended_end():
    """'9999...' 는 종료 없음이므로 None 이어야 한다."""
    assert parse_period("20260701 ~ 99991231") == (date(2026, 7, 1), None)


# ---------------------------------------------------------------------------
# js_call_args — onclick/href 안의 JavaScript 인자 파싱
# ---------------------------------------------------------------------------
def test_js_call_args_heungkuk_fire():
    src = "fn_filedownX('/Upload/gongsi/goods/','제도성 특별약관(유병력자) 기초서류.pdf', '1783058243332249.pdf'); return false;"
    assert js_call_args(src, "fn_filedownX") == [
        "/Upload/gongsi/goods/",
        "제도성 특별약관(유병력자) 기초서류.pdf",
        "1783058243332249.pdf",
    ]


def test_js_call_args_ibk():
    src = "onDownload('HP_PBANO_PDT_SP','675','#1'); return false;"
    assert js_call_args(src, "onDownload") == ["HP_PBANO_PDT_SP", "675", "#1"]


def test_js_call_args_im_life_keeps_commas_inside_quotes():
    src = "javascript:fileDownload('/Download/21. iM 키맨정기보험, 무2404_약관.pdf');"
    assert js_call_args(src, "fileDownload") == ["/Download/21. iM 키맨정기보험, 무2404_약관.pdf"]


def test_js_call_args_missing_function():
    assert js_call_args("javascript:void(0)", "fileDownload") == []
    assert js_call_args("", "fileDownload") == []


# ---------------------------------------------------------------------------
# absolute — 상대 URL 변환
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "base,href,expected",
    [
        # DB생명: /notice/product/sale 기준 상대 경로
        ("https://www.idblife.com/notice/product/sale", "file/3239/1",
         "https://www.idblife.com/notice/product/file/3239/1"),
        ("https://www.idblife.com/notice/product/sale", "prov/sale/9425",
         "https://www.idblife.com/notice/product/prov/sale/9425"),
        # 절대 경로
        ("https://brand.metlife.co.kr", "/pn/mcvrgProd/mcvrgProdDownloadFile.do?fnum=01",
         "https://brand.metlife.co.kr/pn/mcvrgProd/mcvrgProdDownloadFile.do?fnum=01"),
        # 이미 절대 URL
        ("https://a.example", "https://b.example/x.pdf", "https://b.example/x.pdf"),
    ],
)
def test_absolute(base, href, expected):
    assert absolute(base, href) == expected


@pytest.mark.parametrize("href", ["javascript:void(0)", "javascript:stop();", "#", "", None])
def test_absolute_rejects_non_links(href):
    assert absolute("https://a.example/x", href) == ""


# ---------------------------------------------------------------------------
# HTML 파서
# ---------------------------------------------------------------------------
HTML = """
<table class="tblList">
  <thead><tr><th>구분</th><th>상품명</th><th>판매기간</th></tr></thead>
  <tbody>
    <tr><th class="bgW">보장</th><td>무배당 A보험</td><td>2026.07.01 ~ </td></tr>
    <tr><td>보장</td><td>무배당 B보험</td><td>2026.01.01 ~ 2026.06.30</td></tr>
  </tbody>
</table>
"""


def test_table_rows_skips_header():
    table = soup(HTML).select_one("table")
    rows = table_rows(table)
    assert len(rows) == 2


def test_table_rows_none():
    assert table_rows(None) == []


def test_clean_collapses_whitespace():
    assert clean("  무배당 \n\t 프로미라이프  ") == "무배당 프로미라이프"
    assert clean(None) == ""


# ---------------------------------------------------------------------------
# 인코딩
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, content, content_type):
        self.content = content
        self.headers = {"content-type": content_type}


def test_decode_body_euckr():
    text = "판매상품 중 개인연금"
    response = _FakeResponse(text.encode("euc-kr"), "text/html; charset=EUC-KR")
    assert decode_body(response) == text


def test_decode_body_falls_back_when_charset_wrong():
    """헤더가 UTF-8 이라고 해도 실제가 EUC-KR 이면 fallback 으로 복구한다."""
    text = "상품요약서"
    response = _FakeResponse(text.encode("euc-kr"), "text/html; charset=utf-8")
    assert decode_body(response, "euc-kr") == text
