"""신규 보험사 Adapter 들이 공유하는 파싱/요청 유틸.

기존 5개사(DB/LOTTE/MERITZ/KB/SAMSUNG) Adapter 는 이 모듈을 import 하지 않습니다.
따라서 이 모듈의 변경이 기존 5개사 동작에 영향을 주지 않습니다.
"""

from __future__ import annotations

import json
import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from utils.date_utils import parse_date

__all__ = [
    "soup",
    "absolute",
    "clean",
    "parse_period",
    "js_call_args",
    "decode_body",
    "json_post",
    "table_rows",
]


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def soup(markup: str) -> BeautifulSoup:
    """lxml 파서를 사용하는 BeautifulSoup 인스턴스."""
    return BeautifulSoup(markup or "", "lxml")


def clean(value) -> str:
    """노드/문자열에서 공백을 정리한 텍스트를 얻는다."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else value.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def table_rows(table) -> list:
    """thead 를 제외한 데이터 행 목록."""
    if table is None:
        return []
    body = table.find("tbody") or table
    return [tr for tr in body.find_all("tr") if tr.find(["td", "th"])]


def absolute(base: str, href: str) -> str:
    """상대 URL 을 절대 URL 로 변환한다. 이미 절대면 그대로."""
    href = (href or "").strip()
    if not href or href.lower().startswith(("javascript:", "#", "mailto:")):
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return urljoin(base, href)


# ---------------------------------------------------------------------------
# 날짜 / 판매기간
# ---------------------------------------------------------------------------
_PERIOD_RE = re.compile(
    r"(\d{4}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}|\d{8})"
    r"\s*(?:~|-|부터|∼)\s*"
    r"(\d{4}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}|\d{8})?"
)
_SINGLE_DATE_RE = re.compile(r"(\d{4}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}|\d{8})")


def parse_period(text: str) -> tuple[date | None, date | None]:
    """'2026.07.01 ~ ' / '2026-07-01 ~ 2026-12-31' / '20260701~현재' 를 (시작, 종료)로.

    종료가 비어 있거나 '현재'/'9999...' 면 None(판매중)을 돌려준다.
    """
    text = clean(text)
    if not text:
        return None, None
    m = _PERIOD_RE.search(text)
    if m:
        return parse_date(m.group(1)), parse_date(m.group(2)) if m.group(2) else None
    m = _SINGLE_DATE_RE.search(text)
    if m:
        return parse_date(m.group(1)), None
    return None, None


# ---------------------------------------------------------------------------
# JavaScript 링크 해석
# ---------------------------------------------------------------------------
_ARG_RE = re.compile(r"""'([^']*)'|"([^"]*)"|([^,()'"]+)""")


def js_call_args(source: str, func: str) -> list[str]:
    """``onclick="fn_filedownX('/a/','b.pdf','c.pdf')"`` 에서 인자 목록을 뽑는다.

    함수 호출을 찾지 못하면 빈 리스트를 돌려준다.
    """
    if not source or not func:
        return []
    idx = source.find(func + "(")
    if idx < 0:
        return []
    start = idx + len(func) + 1
    depth = 1
    end = start
    while end < len(source) and depth:
        ch = source[end]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
        end += 1
    inner = source[start:end]
    args = []
    for part in _split_args(inner):
        part = part.strip()
        if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'":
            part = part[1:-1]
        args.append(part)
    return args


def _split_args(inner: str) -> list[str]:
    """따옴표 안의 콤마를 무시하고 인자를 나눈다."""
    out, buf, quote_ch = [], [], ""
    for ch in inner:
        if quote_ch:
            if ch == quote_ch:
                quote_ch = ""
            buf.append(ch)
        elif ch in "\"'":
            quote_ch = ch
            buf.append(ch)
        elif ch == ",":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


# ---------------------------------------------------------------------------
# 인코딩 / 요청
# ---------------------------------------------------------------------------
def decode_body(response, fallback: str = "utf-8") -> str:
    """Content-Type charset 을 신뢰하되 깨지면 대체 인코딩으로 다시 디코딩한다."""
    charset = ""
    ctype = response.headers.get("content-type", "")
    m = re.search(r"charset=([\w\-]+)", ctype, re.I)
    if m:
        charset = m.group(1).lower()
    for enc in [charset, fallback, "utf-8", "euc-kr", "cp949"]:
        if not enc:
            continue
        try:
            return response.content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return response.content.decode("utf-8", errors="replace")


def json_post(client, url: str, payload: dict, *, referer: str = "", timeout: float | None = None):
    """``Content-Type: application/json`` 으로 POST 한다."""
    headers = {"Content-Type": "application/json;charset=UTF-8", "X-Requested-With": "XMLHttpRequest"}
    if referer:
        headers["Referer"] = referer
    kwargs = {"content": json.dumps(payload, ensure_ascii=False).encode("utf-8"), "headers": headers}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return client.post(url, **kwargs)
