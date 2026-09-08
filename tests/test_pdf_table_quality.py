"""PDF table significance rules."""

from __future__ import annotations

import pytest

from app.domain.pdf_load import TableQualityStatus
from app.infrastructure.pdf.prosure.table_quality import (
    assess_table,
    bbox_contains,
    overlap_ratio,
    table_fingerprint,
    table_text_fingerprint,
)


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        ([], "EMPTY_TABLE"),
        ([["상 품 요 약 서"]], "SINGLE_CELL_LAYOUT"),
        ([["구분", "가입조건", "비고"]], "HEADER_ONLY"),
    ],
)
def test_clear_layout_candidates_are_rejected(rows, reason: str) -> None:
    assessment = assess_table(rows)

    assert assessment.status is TableQualityStatus.REJECTED
    assert assessment.reason == reason


def test_single_row_with_values_is_preserved_as_fragment() -> None:
    assessment = assess_table([["20년", "50,000,000", "100.0%"]])

    assert assessment.status is TableQualityStatus.FRAGMENT
    assert assessment.reason == "SINGLE_ROW_DATA_FRAGMENT"


def test_single_row_categorical_key_value_is_preserved_as_fragment() -> None:
    assessment = assess_table([["보험기간", "종신"]])

    assert assessment.status is TableQualityStatus.FRAGMENT


def test_short_one_column_benefit_list_is_not_treated_as_split_word() -> None:
    assessment = assess_table([["암"], ["뇌"], ["치아"]])

    assert assessment.status is TableQualityStatus.FRAGMENT


def test_one_character_column_is_preserved_until_parent_duplicate_check() -> None:
    assessment = assess_table([["종"], ["신"], ["연"], ["금"]])

    assert assessment.status is TableQualityStatus.FRAGMENT
    assert assessment.reason == "SPLIT_TEXT_FRAGMENT"


def test_one_column_content_is_preserved_as_fragment() -> None:
    assessment = assess_table([["기준나이"], ["45세 가입"]])

    assert assessment.status is TableQualityStatus.FRAGMENT
    assert assessment.reason == "ONE_COLUMN_FRAGMENT"


@pytest.mark.parametrize(
    "rows",
    [
        [["항목", "값"], ["기본", "적용"]],
        [["문: 연금은 언제 지급하나요?", ""], ["", "답: 매월 지급합니다."]],
        [["기간", "해약환급금"], ["20년", "50,000,000"]],
    ],
)
def test_relational_tables_are_meaningful(rows) -> None:
    assessment = assess_table(rows)

    assert assessment.status is TableQualityStatus.MEANINGFUL


def test_header_grid_near_page_end_is_preserved_as_fragment() -> None:
    assessment = assess_table(
        [["기간", "납입보험료", "환급률"], ["", "(A)", "(B/A)"]],
        bbox=[10, 700, 500, 820],
        page_height=842,
    )

    assert assessment.status is TableQualityStatus.FRAGMENT
    assert assessment.reason == "HEADER_FRAGMENT_NEAR_PAGE_END"


def test_overlap_helpers_only_match_contained_or_near_identical_regions() -> None:
    outer = [0, 0, 200, 200]
    inner = [20, 20, 100, 100]
    separate = [220, 0, 320, 100]

    assert bbox_contains(outer, inner)
    assert not bbox_contains(outer, separate)
    assert overlap_ratio(inner, [20.2, 20.2, 99.8, 99.8]) > 0.95
    assert overlap_ratio(inner, separate) == 0


def test_table_fingerprint_ignores_spacing_and_punctuation() -> None:
    assert table_fingerprint([["기준 나이", "(45세 가입)"]]) == table_fingerprint(
        [["기준나이", "45세 가입"]]
    )


def test_table_fingerprint_preserves_shape_but_text_fingerprint_does_not() -> None:
    horizontal = [["보험기간", "종신"]]
    vertical = [["보험기간"], ["종신"]]

    assert table_fingerprint(horizontal) != table_fingerprint(vertical)
    assert table_text_fingerprint(horizontal) == table_text_fingerprint(vertical)
