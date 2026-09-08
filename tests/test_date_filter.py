"""대상 월 계산 / 판매기간 중첩 / 버전 선정 테스트."""

from datetime import date

import pytest

from models.product_version import DateBasis, ProductVersion
from utils.date_utils import (
    date_range,
    month_range,
    overlaps_month,
    parse_date,
    period_scope_key,
    select_versions,
)


# 1. 대상 월 시작일/종료일 계산 ------------------------------------------------
@pytest.mark.parametrize(
    "target_month,expected",
    [
        ("2026-07", (date(2026, 7, 1), date(2026, 7, 31))),
        ("2026-02", (date(2026, 2, 1), date(2026, 2, 28))),
        ("2024-02", (date(2024, 2, 1), date(2024, 2, 29))),  # 윤년
        ("2026-12", (date(2026, 12, 1), date(2026, 12, 31))),
    ],
)
def test_month_range(target_month, expected):
    assert month_range(target_month) == expected


@pytest.mark.parametrize("bad", ["2026-13", "202607", "", "2026-7", None])
def test_month_range_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        month_range(bad)


def test_date_range_and_scope_key():
    start, end = date_range("2024-01-01", "2026-08-20")
    assert (start, end) == (date(2024, 1, 1), date(2026, 8, 20))
    assert period_scope_key(start, end) == "20240101_20260820"


@pytest.mark.parametrize(
    "start,end",
    [("2024-01-01", "2023-12-31"), ("2024-1-01", "2024-02-01"), ("2024-02-30", "2024-03-01")],
)
def test_date_range_rejects_invalid_or_reversed(start, end):
    with pytest.raises(ValueError):
        date_range(start, end)


def test_parse_date_variants():
    assert parse_date("20260701") == date(2026, 7, 1)
    assert parse_date("2026.07.01") == date(2026, 7, 1)
    assert parse_date("2026-07-01") == date(2026, 7, 1)
    assert parse_date(20260701) == date(2026, 7, 1)
    # '종료 없음' 표현과 파싱 불가 값
    assert parse_date("99991231") is None
    assert parse_date("현재") is None
    assert parse_date("-") is None
    assert parse_date("") is None
    assert parse_date(None) is None
    assert parse_date("20261301") is None   # 존재하지 않는 월


# 2. 판매기간과 대상 월 중첩 판정 ----------------------------------------------
MONTH_START, MONTH_END = date(2026, 7, 1), date(2026, 7, 31)


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (date(2026, 7, 15), None, True),                       # 월 중 시작, 종료 없음
        (date(2026, 1, 1), None, True),                        # 이전 시작, 판매중
        (date(2026, 1, 1), date(2026, 7, 1), True),            # 경계: 종료일 == 월 시작일
        (date(2026, 7, 31), date(2026, 12, 31), True),         # 경계: 시작일 == 월 종료일
        (date(2026, 1, 1), date(2026, 6, 30), False),          # 월 이전에 종료
        (date(2026, 8, 1), None, False),                       # 월 이후 시작
        (None, date(2026, 7, 10), True),                       # 시작일 불명 + 종료일이 월 이후
        (None, date(2026, 6, 1), False),                       # 시작일 불명 + 종료일이 월 이전
    ],
)
def test_overlaps_month(start, end, expected):
    assert overlaps_month(start, end, MONTH_START, MONTH_END) is expected


# 10. 동일 상품의 여러 버전 분리 -----------------------------------------------
def _version(name, start, end=None, revision=None, product_id="P1"):
    return ProductVersion(
        company_code="TEST",
        company_name="테스트손해보험",
        product_name_raw=name,
        source_page_url="https://example.test",
        source_product_id=product_id,
        sale_start_date=start,
        sale_end_date=end,
        revision_date=revision,
    )


def test_select_new_or_revised_keeps_only_target_month():
    versions = [
        _version("A보험", date(2026, 6, 1)),
        _version("A보험", date(2026, 7, 1)),
        _version("A보험", date(2026, 7, 20)),
        _version("A보험", date(2026, 8, 1)),
    ]
    selected = select_versions(versions, MONTH_START, MONTH_END, "new_or_revised")
    assert [v.sale_start_date for v in selected] == [date(2026, 7, 1), date(2026, 7, 20)]
    # 같은 상품이라도 버전은 개별 항목으로 남는다.
    assert len({v.resolved_version_key() for v in selected}) == 2


def test_select_overlap_mode_includes_ongoing_versions():
    versions = [
        _version("A보험", date(2026, 1, 1), date(2026, 6, 30)),   # 겹치지 않음
        _version("A보험", date(2026, 1, 1), None),                # 판매중
        _version("A보험", date(2026, 7, 5), None),
    ]
    selected = select_versions(versions, MONTH_START, MONTH_END, "overlap")
    assert len(selected) == 2


def test_versions_without_date_are_kept_for_manual_review():
    versions = [_version("날짜없음보험", None)]
    selected = select_versions(versions, MONTH_START, MONTH_END, "new_or_revised")
    assert len(selected) == 1
    assert selected[0].needs_manual_review is True
    assert selected[0].date_basis == DateBasis.NONE
    assert selected[0].resolved_version_key() == "UNKNOWN_VERSION"


@pytest.mark.parametrize("mode", ["new_or_revised", "overlap"])
def test_versions_without_start_date_but_ended_before_month_are_excluded(mode):
    versions = [
        _version("과거종료보험", None, end=date(2014, 12, 31)),
        _version("종료일도모름", None),
        _version("대상월종료보험", None, end=date(2026, 7, 1)),
    ]

    selected = select_versions(versions, MONTH_START, MONTH_END, mode)

    assert [version.product_name_raw for version in selected] == [
        "종료일도모름",
        "대상월종료보험",
    ]


def test_date_basis_priority_prefers_revision_date():
    version = _version("A보험", date(2026, 7, 1), revision=date(2026, 7, 15))
    assert version.target_date == date(2026, 7, 15)
    assert version.date_basis == DateBasis.REVISION_DATE

    version2 = _version("B보험", date(2026, 7, 1))
    assert version2.date_basis == DateBasis.SALE_START_DATE

    version3 = _version("C보험", None)
    version3.disclosure_date = date(2026, 7, 3)
    assert version3.date_basis == DateBasis.DISCLOSURE_DATE


def test_select_versions_rejects_unknown_mode():
    with pytest.raises(ValueError):
        select_versions([], MONTH_START, MONTH_END, "nope")
