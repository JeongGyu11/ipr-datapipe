"""보수적인 반복 헤더·푸터 검출과 감사 정보 생성."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable

MINIMUM_PAGE_COUNT = 3
CANDIDATE_ZONE_RATIO = 0.10
FREQUENCY_THRESHOLD = 0.80
LINE_GROUP_THRESHOLD = 3.0

_PAGE_FRACTION = re.compile(
    r"\b(?:(?:page|페이지|p\.?)[ ]*)?\d+[ ]*(?:/|of)[ ]*\d+\b",
    re.IGNORECASE,
)
_PAGE_LABEL = re.compile(r"\b(?:page|페이지|p\.?)[ ]*\d+\b", re.IGNORECASE)
_STANDALONE_PAGE_NUMBER = re.compile(r"^\s*[-–—]?\s*\d+\s*[-–—]?\s*$")
_WHITESPACE = re.compile(r"\s+")


def normalize_candidate(text: str) -> str:
    """페이지 번호처럼 변하는 숫자를 제외하고 반복 비교용 문자열을 만든다."""

    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    normalized = _PAGE_FRACTION.sub("<page>", normalized)
    normalized = _PAGE_LABEL.sub("<page>", normalized)
    if _STANDALONE_PAGE_NUMBER.fullmatch(normalized):
        normalized = "<page>"
    return _WHITESPACE.sub(" ", normalized).strip()


def group_words_to_lines(
    words: Iterable[dict[str, Any]],
    threshold: float = LINE_GROUP_THRESHOLD,
) -> list[dict[str, Any]]:
    """pdfplumber 단어를 좌표와 원문을 보존한 시각적 행으로 묶는다."""

    ordered = sorted(
        list(words or []),
        key=lambda word: (float(word.get("top", 0)), float(word.get("x0", 0))),
    )
    if not ordered:
        return []

    grouped: list[list[dict[str, Any]]] = []
    for word in ordered:
        top = float(word.get("top", 0))
        if not grouped or abs(top - float(grouped[-1][0].get("top", 0))) > threshold:
            grouped.append([word])
        else:
            grouped[-1].append(word)

    lines: list[dict[str, Any]] = []
    for group in grouped:
        group.sort(key=lambda word: float(word.get("x0", 0)))
        text = " ".join(str(word.get("text", "")) for word in group).strip()
        if not text:
            continue
        lines.append(
            {
                "text": text,
                "normalized_text": normalize_candidate(text),
                "bbox": [
                    min(float(word.get("x0", 0)) for word in group),
                    min(float(word.get("top", 0)) for word in group),
                    max(float(word.get("x1", 0)) for word in group),
                    max(float(word.get("bottom", 0)) for word in group),
                ],
            }
        )
    return lines


def analyze_header_footer(
    pdf: Any,
    *,
    enabled: bool = False,
    words_by_page: dict[int, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """반복 행을 검출한다 (제거 적용 여부는 ``enabled``로 결정한다).

    OCR 품질 판정에는 헤더·푸터 제거 옵션과 무관하게 반복 행의 좌표가
    필요하다.  따라서 ``enabled=False``여도 검출을 수행하되, ``applied``는
    계속 거짓으로 유지하여 기존 공개 산출물의 의미를 보존한다.
    """

    pages = list(getattr(pdf, "pages", []) or [])
    analysis: dict[str, Any] = {
        "enabled": enabled,
        "applied": False,
        "page_count": len(pages),
        "minimum_page_count": MINIMUM_PAGE_COUNT,
        "candidate_zone_ratio": CANDIDATE_ZONE_RATIO,
        "frequency_threshold": FREQUENCY_THRESHOLD,
        "required_page_count": 0,
        "pages": [],
        "removed_lines": [],
        "crop_header_fraction": 0.0,
        "crop_footer_fraction": 1.0,
    }
    if len(pages) < MINIMUM_PAGE_COUNT:
        return analysis

    candidates: list[dict[str, Any]] = []
    page_entries: list[dict[str, Any]] = []
    for page_no, page in enumerate(pages, start=1):
        height = float(getattr(page, "height", 0) or 0)
        if words_by_page is not None and page_no in words_by_page:
            words = words_by_page[page_no]
        else:
            try:
                words = page.extract_words() or []
            except Exception:
                words = []
        lines = group_words_to_lines(words)
        page_candidates: list[dict[str, Any]] = []
        if height > 0:
            for line in lines:
                top, bottom = float(line["bbox"][1]), float(line["bbox"][3])
                center = (top + bottom) / 2
                location = "HEADER" if center <= height * CANDIDATE_ZONE_RATIO else None
                if center >= height * (1.0 - CANDIDATE_ZONE_RATIO):
                    location = "FOOTER"
                if location is None or not line["normalized_text"]:
                    continue
                candidate = {
                    **line,
                    "page_no": page_no,
                    "location": location,
                    "page_height": height,
                }
                candidates.append(candidate)
                page_candidates.append(candidate)
        page_entries.append({"page_no": page_no, "candidates": page_candidates})

    pages_by_key: dict[tuple[str, str], set[int]] = defaultdict(set)
    for candidate in candidates:
        pages_by_key[(candidate["location"], candidate["normalized_text"])].add(
            candidate["page_no"]
        )

    required = max(MINIMUM_PAGE_COUNT, math.ceil(len(pages) * FREQUENCY_THRESHOLD))
    accepted = {key for key, page_numbers in pages_by_key.items() if len(page_numbers) >= required}
    removed: list[dict[str, Any]] = []
    for entry in page_entries:
        for candidate in entry["candidates"]:
            key = (candidate["location"], candidate["normalized_text"])
            match_count = len(pages_by_key[key])
            candidate["match_page_count"] = match_count
            candidate["removed"] = key in accepted
            if key in accepted:
                removed.append(candidate)

    header_ratios = [
        float(line["bbox"][3]) / float(line["page_height"])
        for line in removed
        if line["location"] == "HEADER"
    ]
    footer_ratios = [
        float(line["bbox"][1]) / float(line["page_height"])
        for line in removed
        if line["location"] == "FOOTER"
    ]
    analysis.update(
        {
            "applied": bool(enabled and removed),
            "required_page_count": required,
            "pages": page_entries,
            "removed_lines": removed,
            "crop_header_fraction": max(header_ratios, default=0.0),
            "crop_footer_fraction": min(footer_ratios, default=1.0),
        }
    )
    return analysis


def compute_header_footer_bounds(pdf: Any) -> tuple[float, float]:
    """기존 호출부 호환용으로 안전하게 검출된 crop 경계만 반환한다."""

    analysis = analyze_header_footer(pdf, enabled=True)
    return (
        float(analysis["crop_header_fraction"]),
        float(analysis["crop_footer_fraction"]),
    )


__all__ = [
    "CANDIDATE_ZONE_RATIO",
    "FREQUENCY_THRESHOLD",
    "MINIMUM_PAGE_COUNT",
    "analyze_header_footer",
    "compute_header_footer_bounds",
    "group_words_to_lines",
    "normalize_candidate",
]
