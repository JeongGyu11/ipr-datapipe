"""대상 월/기간 계산 및 상품 버전 날짜 필터."""

from __future__ import annotations

import calendar
import re
from datetime import date

_DIGITS = re.compile(r"\d")

#: 사이트가 '종료 없음'을 표현하는 값들
_OPEN_ENDED = {"99991231", "99991230", "-", "", "현재", "9999.12.31"}


def month_range(target_month: str) -> tuple[date, date]:
    """'YYYY-MM' -> (해당 월 1일, 해당 월 말일).

    >>> month_range("2026-07")
    (datetime.date(2026, 7, 1), datetime.date(2026, 7, 31))
    """
    if not re.fullmatch(r"\d{4}-\d{2}", target_month or ""):
        raise ValueError(f"target_month 형식이 올바르지 않습니다: {target_month!r} (예: 2026-07)")
    year, month = (int(x) for x in target_month.split("-"))
    if not 1 <= month <= 12:
        raise ValueError(f"target_month 의 월 값이 올바르지 않습니다: {target_month!r}")
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def date_range(start: str | date, end: str | date) -> tuple[date, date]:
    """정규화된 날짜 범위를 돌려준다.

    CLI에서 사용하는 ``YYYY-MM-DD`` 표기를 엄격히 검증한다. ``date``
    객체를 직접 넘기는 호출도 허용해 Manager/테스트에서 재사용할 수 있다.
    종료일은 시작일보다 빠를 수 없다.
    """
    start_date = _parse_iso_date(start, "start_date")
    end_date = _parse_iso_date(end, "end_date")
    if end_date < start_date:
        raise ValueError(f"end_date가 start_date보다 빠릅니다: {start_date} > {end_date}")
    return start_date, end_date


def period_scope_key(start: date, end: date) -> str:
    """기간 실행의 경로/체크포인트 식별자."""
    return f"{start:%Y%m%d}_{end:%Y%m%d}"


def _parse_iso_date(value: str | date, label: str) -> date:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError(f"{label} 형식이 올바르지 않습니다: {value!r} (예: 2024-01-01)")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} 날짜가 올바르지 않습니다: {value!r}") from exc


def parse_date(value) -> date | None:
    """사이트마다 제각각인 날짜 표기를 date 로 변환한다.

    허용: '20260701', '2026.07.01', '2026-07-01', '2026/07/01', 20260701(int)
    '99991231' 등 '종료 없음' 표현과 파싱 불가 값은 None 을 돌려준다.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text in _OPEN_ENDED:
        return None
    digits = "".join(_DIGITS.findall(text))
    if len(digits) != 8:
        return None
    if digits.startswith("9999"):
        return None
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


def is_open_ended(value) -> bool:
    """판매종료일이 '종료 없음'(판매중)을 의미하는지."""
    if value is None:
        return True
    return str(value).strip() in _OPEN_ENDED


def in_month(target: date | None, start: date, end: date) -> bool:
    """단일 날짜가 대상 월 안에 있는지."""
    return target is not None and start <= target <= end


def overlaps_month(
    sale_start: date | None,
    sale_end: date | None,
    month_start: date,
    month_end: date,
) -> bool:
    """판매기간이 대상 월과 겹치는지.

        상품 버전 시작일 <= 대상 월 종료일
        AND (종료일이 없거나 종료일 >= 대상 월 시작일)
    """
    if sale_start is None:
        # 시작일을 모르면 종료일만으로 판단한다.
        return sale_end is None or sale_end >= month_start
    if sale_start > month_end:
        return False
    return sale_end is None or sale_end >= month_start


def select_versions(versions, month_start: date, month_end: date, mode: str = "new_or_revised"):
    """대상 월에 해당하는 상품 버전을 고른다.

    mode
      new_or_revised : 대상 월에 새로 등록/개정된 버전 (target_date 가 대상 월 안)
      overlap        : 판매기간이 대상 월과 겹치는 모든 버전

    기준 날짜가 없더라도 판매종료일이 대상 월 이전이면 이미 종료된 상품으로
    확정할 수 있으므로 제외한다. 종료 여부까지 판단할 수 없는 버전만 포함해
    호출 측에서 MANUAL_REVIEW_REQUIRED 로 기록한다.
    """
    if mode not in ("new_or_revised", "overlap"):
        raise ValueError(f"알 수 없는 date_selection.mode: {mode!r}")

    selected = []
    for v in versions:
        if v.needs_manual_review:
            if v.sale_end_date is not None and v.sale_end_date < month_start:
                continue
            selected.append(v)
            continue
        if mode == "new_or_revised":
            if in_month(v.target_date, month_start, month_end):
                selected.append(v)
        else:
            if overlaps_month(v.sale_start_date, v.sale_end_date, month_start, month_end):
                selected.append(v)
    return selected
