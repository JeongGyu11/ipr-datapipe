"""메리츠/삼성/미래에셋 목록 단계의 기간 후보 선별 회귀 테스트."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from crawler.adapters.meritz_insurance import MeritzInsuranceAdapter
from crawler.adapters.mirae_life import MiraeLifeAdapter
from crawler.adapters.samsung_insurance import SamsungInsuranceAdapter
from crawler.validators import DocumentClassifier
from tests.company_fixtures import company_definition


START, END = date(2026, 7, 1), date(2026, 7, 31)
CLASSIFIER = DocumentClassifier(
    {"policy": ["약관"], "summary": ["요약서"], "method": ["방법서"]}, []
)


def _adapter(cls, code: str, mode: str = "new_or_revised"):
    return cls(
        company_definition(code, code),
        SimpleNamespace(date_selection_mode=mode),
        CLASSIFIER,
    )


def test_meritz_overlap_keeps_older_version_and_filters_expired_version():
    adapter = _adapter(MeritzInsuranceAdapter, "MERITZ", "overlap")

    assert adapter._is_candidate(date(2024, 1, 1), None, None, START, END)
    assert adapter._is_candidate(date(2026, 7, 31), date(2026, 8, 1), None, START, END)
    assert not adapter._is_candidate(date(2024, 1, 1), date(2026, 6, 30), None, START, END)
    # 날짜 미상 행은 공통 selector의 수동검토 대상으로 남긴다.
    assert adapter._is_candidate(None, None, None, START, END)


def test_meritz_new_mode_uses_start_date_then_disclosure_fallback():
    adapter = _adapter(MeritzInsuranceAdapter, "MERITZ", "new_or_revised")

    # 판매개시일이 대상 기간 이전이면 공시일이 기간 안이어도 버전 기준일
    # 우선순위(판매개시일)를 유지하여 제외한다.
    assert not adapter._is_candidate(date(2024, 1, 1), None, date(2026, 7, 1), START, END)
    # 판매개시일 자체가 없을 때만 공시일을 fallback으로 사용한다.
    assert adapter._is_candidate(None, None, date(2026, 7, 1), START, END)


def test_samsung_materializes_only_candidates_but_keeps_unknown(monkeypatch):
    adapter = _adapter(SamsungInsuranceAdapter, "SAMSUNG")
    rows = [
        {"prdName": "대상", "saleStDt": "20260701", "saleEnDt": "", "prdfilename1": "/a.pdf"},
        {"prdName": "이전", "saleStDt": "20260630", "saleEnDt": "", "prdfilename1": "/b.pdf"},
        {"prdName": "미상", "saleStDt": "", "saleEnDt": "", "prdfilename1": "/c.pdf"},
    ]
    monkeypatch.setattr(adapter, "_fetch_list", lambda: rows)

    versions = adapter.collect_product_versions(START, END)

    assert [v.product_name_raw for v in versions] == ["대상", "미상"]
    assert [d.original_filename for d in versions[0].documents] == ["a.pdf"]
    assert adapter.stats == {
        "api_rows": 3,
        "raw_rows": 3,
        "materialized_rows": 2,
        "filtered_rows": 1,
        "unknown_dates": 1,
        "status_coverage_complete": True,
    }


def test_samsung_overlap_keeps_inclusive_boundaries_and_unknown():
    adapter = _adapter(SamsungInsuranceAdapter, "SAMSUNG", "overlap")

    assert adapter._is_candidate(date(2024, 1, 1), date(2026, 7, 1), START, END)
    assert adapter._is_candidate(date(2026, 7, 31), date(2026, 8, 1), START, END)
    assert not adapter._is_candidate(date(2026, 8, 1), None, START, END)
    assert adapter._is_candidate(None, date(2026, 6, 30), START, END)


class _Response:
    status_code = 200

    def __init__(self, rows):
        self._rows = rows

    def json(self):
        return {"list": self._rows}


def _mirae_row(seq: int, start: str, end: str = ""):
    cells = {
        "cell0": "건강",
        "cell1": f"상품-{seq}",
        "cell2": start,
        "cell3": end,
        "cell4": f"summary-{seq}.pdf",
        "cell5": f"policy-{seq}.pdf",
        "cell6": f"method-{seq}.pdf",
        "cell7": f"/dir-{seq}",
    }
    return {"seq": seq, "jsonData": json.dumps(cells, ensure_ascii=False)}


def test_mirae_reads_duplicate_pages_without_early_sort_stop_and_filters(monkeypatch):
    adapter = _adapter(MiraeLifeAdapter, "MIRAE_LIFE")
    calls = []

    def post(url, *, data, headers):
        calls.append((data["text1"], data["pageNum"]))
        page = int(data["pageNum"])
        if page == 0:
            return _Response(
                [
                    _mirae_row(1, "20260701"),
                    _mirae_row(2, "20260630"),
                    _mirae_row(3, ""),
                ]
            )
        if page == 1:
            # 중복 행만 반환되어도 다음 페이지를 조회해야 한다.
            return _Response([_mirae_row(1, "20260701")])
        return _Response([])

    adapter._client = SimpleNamespace(post=post)
    versions = adapter.collect_product_versions(START, END)

    assert len(calls) == 6  # 판매중/판매중지 각각 0, 1, 2 페이지
    assert [v.product_name_raw for v in versions] == ["상품-1", "상품-3", "상품-1", "상품-3"]
    assert adapter.stats["api_rows"] == 8
    assert adapter.stats["raw_rows"] == 6
    assert adapter.stats["materialized_rows"] == 4
    assert adapter.stats["filtered_rows"] == 2
    assert adapter.stats["unknown_dates"] == 2
    # 기간 선별 전후에도 다운로드 hint/문서 메타데이터는 동일하다.
    assert [d.download_hint["fileName"] for d in versions[0].documents] == [
        "summary-1.pdf",
        "policy-1.pdf",
        "method-1.pdf",
    ]


def test_mirae_overlap_boundaries_and_unknown_are_preserved():
    adapter = _adapter(MiraeLifeAdapter, "MIRAE_LIFE", "overlap")

    assert adapter._is_candidate(date(2024, 1, 1), date(2026, 7, 1), START, END)
    assert adapter._is_candidate(date(2026, 7, 31), date(2026, 8, 1), START, END)
    assert not adapter._is_candidate(date(2026, 8, 1), None, START, END)
    assert adapter._is_candidate(None, date(2026, 6, 30), START, END)


def test_mirae_missing_seq_uses_raw_fallback_and_preserves_distinct_rows():
    adapter = _adapter(MiraeLifeAdapter, "MIRAE_LIFE")
    first = _mirae_row(10, "20260701")
    second = _mirae_row(11, "20260702")
    first.pop("seq")
    second.pop("seq")
    duplicate = dict(first)
    calls = []

    def post(url, *, data, headers):
        calls.append(data["pageNum"])
        return _Response([first, second, duplicate]) if data["pageNum"] == "0" else _Response([])

    adapter._client = SimpleNamespace(post=post)
    versions = adapter._collect("판매중인상품", "판매중", START, END)

    assert [version.product_name_raw for version in versions] == ["상품-10", "상품-11"]
    assert adapter.stats["raw_rows"] == 2
