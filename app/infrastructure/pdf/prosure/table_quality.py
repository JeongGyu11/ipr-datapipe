"""Deterministic significance checks for PDF table candidates."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from app.domain.pdf_load import TableQualityStatus


_WHITESPACE_PATTERN = re.compile(r"\s+")
# A unit word alone is frequently part of a heading (for example ``가입조건``
# contains ``건``).  A value signal therefore requires a digit or percent sign;
# Korean amount/age/period values naturally include a digit as well.
_VALUE_PATTERN = re.compile(r"\d|%|％")
_RELATION_PATTERN = re.compile(r"[:：?？]")
_CANONICAL_PATTERN = re.compile(r"[^가-힣A-Za-z0-9%]+")
_LONG_CELL_MINIMUM = 10
_HEADER_LABELS = frozenset(
    {
        "구분",
        "항목",
        "내용",
        "비고",
        "가입조건",
        "가입나이",
        "보험기간",
        "납입기간",
        "납입주기",
        "급부명",
        "급부명칭",
        "보장내용",
        "지급사유",
        "지급금액",
        "보험료",
        "납입보험료",
        "해약환급금",
        "환급률",
        "기간",
        "목적",
        "시기",
        "비용",
        "합계",
    }
)


@dataclass(frozen=True)
class TableQualityMetrics:
    row_count: int
    column_count: int
    nonempty_cell_count: int
    multi_cell_row_count: int
    value_cell_count: int
    long_text_cell_count: int
    relation_cell_count: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class TableAssessment:
    status: TableQualityStatus
    reason: str
    metrics: TableQualityMetrics


def _compact(value: str) -> str:
    return _WHITESPACE_PATTERN.sub(" ", value).strip()


def _cells(rows: Sequence[Sequence[str]]) -> list[str]:
    return [_compact(cell) for row in rows for cell in row if _compact(cell)]


def _canonical_cell(value: str) -> str:
    return _CANONICAL_PATTERN.sub("", _compact(value)).lower()


def table_fingerprint(rows: Sequence[Sequence[str]]) -> str:
    """Return a shape-aware fingerprint for exact-overlap duplicate checks."""

    row_count = len(rows)
    column_count = max((len(row) for row in rows), default=0)
    row_parts = [
        "\x1f".join(_canonical_cell(cell) for cell in row)
        for row in rows
    ]
    return f"{row_count}x{column_count}:" + "\x1e".join(row_parts)


def table_text_fingerprint(rows: Sequence[Sequence[str]]) -> str:
    """Return canonical text only for parent/child content containment checks."""

    return "".join(_canonical_cell(cell) for cell in _cells(rows))


def assess_table(
    rows: Sequence[Sequence[str]],
    *,
    bbox: Sequence[float] | None = None,
    page_height: float | None = None,
) -> TableAssessment:
    """Classify a cleaned table without discarding plausible data fragments."""

    row_count = len(rows)
    column_count = max((len(row) for row in rows), default=0)
    nonempty_by_row = [sum(1 for cell in row if _compact(cell)) for row in rows]
    cells = _cells(rows)
    metrics = TableQualityMetrics(
        row_count=row_count,
        column_count=column_count,
        nonempty_cell_count=len(cells),
        multi_cell_row_count=sum(count >= 2 for count in nonempty_by_row),
        value_cell_count=sum(bool(_VALUE_PATTERN.search(cell)) for cell in cells),
        long_text_cell_count=sum(len(cell) >= _LONG_CELL_MINIMUM for cell in cells),
        relation_cell_count=sum(bool(_RELATION_PATTERN.search(cell)) for cell in cells),
    )

    if not cells:
        return TableAssessment(TableQualityStatus.REJECTED, "EMPTY_TABLE", metrics)
    if len(cells) == 1:
        return TableAssessment(
            TableQualityStatus.REJECTED,
            "SINGLE_CELL_LAYOUT",
            metrics,
        )

    has_content_signal = any(
        (
            metrics.value_cell_count,
            metrics.long_text_cell_count,
            metrics.relation_cell_count,
        )
    )
    if row_count == 1:
        canonical_cells = {_canonical_cell(cell) for cell in cells}
        if not has_content_signal and canonical_cells <= _HEADER_LABELS:
            return TableAssessment(
                TableQualityStatus.REJECTED,
                "HEADER_ONLY",
                metrics,
            )
        return TableAssessment(
            TableQualityStatus.FRAGMENT,
            "SINGLE_ROW_DATA_FRAGMENT",
            metrics,
        )

    if column_count == 1:
        # A one-character list can still carry real insurance categories
        # (A/B/C, 남/여, 암/뇌).  Preserve it unless the parser later proves
        # that the same text is already contained by a meaningful parent table.
        reason = (
            "SPLIT_TEXT_FRAGMENT"
            if len(cells) >= 3
            and not has_content_signal
            and all(len(cell) == 1 for cell in cells)
            else "ONE_COLUMN_FRAGMENT"
        )
        return TableAssessment(
            TableQualityStatus.FRAGMENT,
            reason,
            metrics,
        )

    near_page_bottom = bool(
        bbox
        and len(bbox) >= 4
        and page_height
        and page_height > 0
        and float(bbox[3]) / page_height >= 0.80
    )
    if near_page_bottom and not has_content_signal:
        return TableAssessment(
            TableQualityStatus.FRAGMENT,
            "HEADER_FRAGMENT_NEAR_PAGE_END",
            metrics,
        )

    reason = "VALUE_TABLE" if metrics.value_cell_count else "STRUCTURED_TEXT_TABLE"
    return TableAssessment(TableQualityStatus.MEANINGFUL, reason, metrics)


def bbox_contains(
    outer: Sequence[float], inner: Sequence[float], *, tolerance: float = 1.0
) -> bool:
    if len(outer) < 4 or len(inner) < 4:
        return False
    return (
        float(outer[0]) - tolerance <= float(inner[0])
        and float(outer[1]) - tolerance <= float(inner[1])
        and float(outer[2]) + tolerance >= float(inner[2])
        and float(outer[3]) + tolerance >= float(inner[3])
    )


def overlap_ratio(first: Sequence[float], second: Sequence[float]) -> float:
    if len(first) < 4 or len(second) < 4:
        return 0.0
    left = max(float(first[0]), float(second[0]))
    top = max(float(first[1]), float(second[1]))
    right = min(float(first[2]), float(second[2]))
    bottom = min(float(first[3]), float(second[3]))
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, float(first[2]) - float(first[0])) * max(
        0.0, float(first[3]) - float(first[1])
    )
    second_area = max(0.0, float(second[2]) - float(second[0])) * max(
        0.0, float(second[3]) - float(second[1])
    )
    smaller = min(first_area, second_area)
    return intersection / smaller if smaller > 0 else 0.0


def rejection_warning(
    *,
    page_no: int,
    candidate_index: int,
    bbox: Sequence[float],
    assessment: TableAssessment,
) -> dict[str, Any]:
    return {
        "code": "TABLE_CANDIDATE_REJECTED",
        "reason": assessment.reason,
        "page_no": page_no,
        "candidate_index": candidate_index,
        "bbox": [float(value) for value in bbox],
        "metrics": assessment.metrics.as_dict(),
    }


__all__ = [
    "TableAssessment",
    "TableQualityMetrics",
    "assess_table",
    "bbox_contains",
    "overlap_ratio",
    "rejection_warning",
    "table_fingerprint",
    "table_text_fingerprint",
]
