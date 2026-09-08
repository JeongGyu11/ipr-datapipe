"""DB손해보험 Step5 후보/Step4 보강 정책 테스트."""

from datetime import date
from types import SimpleNamespace

import pytest

from crawler.adapters.db_insurance import DBInsuranceAdapter, STEP4
from crawler.validators import DocumentClassifier
from tests.company_fixtures import company_definition


START = date(2024, 1, 1)
END = date(2024, 1, 31)


def _adapter(rows, details=None, mode="new_or_revised"):
    adapter = DBInsuranceAdapter.__new__(DBInsuranceAdapter)
    adapter.code = "DB"
    adapter.name = "DB손해보험"
    adapter.base_url = "https://www.idbins.com/FWMAIV1534.do"
    adapter.config = SimpleNamespace(date_selection_mode=mode)
    adapter.company = company_definition("DB")
    adapter.runtime_options = {}
    adapter.classifier = DocumentClassifier(
        {"policy": ["약관"], "summary": ["요약"], "method": ["방법"]}, []
    )
    adapter.stats = {}
    adapter._active_status_rows = []
    adapter.log = __import__("logging").getLogger("test-db-insurance")
    adapter._search = lambda *_args: rows
    calls = []
    detail_map = details or {}

    def post(path, payload):
        calls.append((path, payload))
        return {"result": [detail_map[payload["sqno"]]]} if payload["sqno"] in detail_map else {}

    adapter._post_json = post
    return adapter, calls


def _row(sqno, start, *, name=None, policy="약관.pdf", on_sale="1"):
    return {
        "SQNO": sqno,
        "PDC_NM": name or f"상품-{sqno}",
        "ARC_KND_LGCG_NM": "장기보험",
        "ARC_PDC_SL_YN": on_sale,
        "SALE_BEGIN_DAY": start,
        "INPL_FINM": policy,
    }


def _detail(start, end=None, **documents):
    return {"SL_STR_DT": start, "SL_FIN_DT": end, **documents}


def test_new_or_revised_calls_step4_only_for_start_date_candidates():
    rows = [_row("old", "2023.12.01"), _row("in", "2024.01.15"), _row("future", "2024.02.01")]
    adapter, calls = _adapter(rows, {"in": _detail("20240115", "20241231")})

    versions = adapter.collect_product_versions(START, END)

    assert [v.source_product_id for v in versions] == ["in"]
    assert [payload["sqno"] for path, payload in calls if path == STEP4] == ["in"]
    assert adapter.stats["step4_attempted"] == 1
    assert adapter.stats["step4_deferred"] == 2
    assert adapter.stats["filtered_rows"] == 2


def test_overlap_excludes_expired_includes_end_boundary_and_defers_future():
    rows = [_row("expired", "2023.12.01"), _row("boundary", "2023.12.01"), _row("future", "2024.02.01")]
    details = {
        "expired": _detail("20231201", "20231231"),
        "boundary": _detail("20231201", "20240101"),
    }
    adapter, calls = _adapter(rows, details, mode="overlap")

    versions = adapter.collect_product_versions(START, END)

    assert [v.source_product_id for v in versions] == ["boundary"]
    assert {payload["sqno"] for path, payload in calls if path == STEP4} == {"expired", "boundary"}
    assert adapter.stats["step4_deferred"] == 1


def test_step4_failure_keeps_candidate_as_ongoing_and_records_stats():
    adapter, calls = _adapter([_row("failed", "2024.01.01")], {})

    versions = adapter.collect_product_versions(START, END)

    assert len(versions) == 1
    assert versions[0].sale_end_date is None
    assert len(calls) == 1
    assert adapter.stats["step4_attempted"] == 1
    assert adapter.stats["step4_succeeded"] == 0
    assert adapter.stats["step4_failed"] == 1


def test_step4_cache_is_once_and_preserves_document_url_and_end_date():
    row = _row("same", "2024.01.10", policy="약관 (01).pdf")
    adapter, calls = _adapter(
        [row, dict(row)],
        {"same": _detail("20240110", "20240630", INPL_FINM="약관 (01).pdf")},
    )

    versions = adapter.collect_product_versions(START, END)

    assert len(versions) == 2
    assert all(v.sale_end_date == date(2024, 6, 30) for v in versions)
    assert all(v.documents[0].document_url.endswith("%EC%95%BD%EA%B4%80%20%2801%29.pdf") for v in versions)
    assert [payload["sqno"] for path, payload in calls if path == STEP4] == ["same"]
    assert adapter.stats["step4_attempted"] == 1


def test_same_sqno_with_different_sale_status_uses_separate_detail_cache_entries():
    rows = [_row("same", "2024.01.01"), _row("same", "2024.01.01", on_sale="0")]
    adapter, calls = _adapter(rows, {"same": _detail("20240101", "20241231")})

    versions = adapter.collect_product_versions(START, END)

    assert len(versions) == 2
    assert [(payload["sqno"], payload["arc_pdc_sl_yn"]) for path, payload in calls] == [
        ("same", "1"),
        ("same", "0"),
    ]
    assert adapter.stats["step4_attempted"] == 2


def test_max_products_caps_step4_requests_without_mutating_catalog_options():
    rows = [_row("first", "2024.01.01"), _row("second", "2024.01.02")]
    adapter, calls = _adapter(
        rows,
        {
            "first": _detail("20240101", "20241231"),
            "second": _detail("20240102", "20241231"),
        },
    )
    adapter.runtime_options = {"max_products": 1}

    versions = adapter.collect_product_versions(START, END)

    assert [version.source_product_id for version in versions] == ["first"]
    assert [payload["sqno"] for path, payload in calls if path == STEP4] == ["first"]
    assert adapter.stats["coverage_capped"] is True
    assert adapter.stats["products_total"] == 2
    assert adapter.stats["products_skipped"] == 1
    assert adapter.stats["status_coverage_complete"] is False


@pytest.mark.parametrize("invalid_limit", [0, -1, 1.5, True, "0", "invalid"])
def test_invalid_max_products_is_rejected(invalid_limit):
    adapter, _calls = _adapter([_row("first", "2024.01.01")])
    adapter.runtime_options = {"max_products": invalid_limit}
    adapter._search = lambda *_args: pytest.fail("invalid limit must fail before Step5")

    with pytest.raises(ValueError, match="1 이상의 정수"):
        adapter.collect_product_versions(START, END)


def test_unknown_start_is_resolved_by_step4_or_preserved_on_failure():
    success, success_calls = _adapter(
        [_row("resolved", "")], {"resolved": _detail("20240115", "20240131")}
    )
    resolved = success.collect_product_versions(START, END)
    assert [v.source_product_id for v in resolved] == ["resolved"]
    assert resolved[0].sale_start_date == date(2024, 1, 15)
    assert len(success_calls) == 1

    failed, failed_calls = _adapter([_row("unknown", "")], {})
    unknown = failed.collect_product_versions(START, END)
    assert [v.source_product_id for v in unknown] == ["unknown"]
    assert unknown[0].sale_start_date is None
    assert len(failed_calls) == 1
    assert failed.stats["step4_failed"] == 1


def test_missing_sqno_is_not_sent_as_literal_none_and_is_preserved_for_review():
    adapter, calls = _adapter([_row(None, "")], {})

    versions = adapter.collect_product_versions(START, END)

    assert len(versions) == 1
    assert versions[0].source_product_id == ""
    assert versions[0].sale_start_date is None
    assert calls == []
    assert adapter.stats["step4_deferred"] == 1
