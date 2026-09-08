"""판매중 manifest 재검증 시 목록 단계 보존 회귀 테스트."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from crawler.adapters.lotte_insurance import LotteInsuranceAdapter
from crawler.adapters.meritz_insurance import MeritzInsuranceAdapter
from crawler.adapters.mirae_life import MiraeLifeAdapter
from crawler.adapters.samsung_insurance import SamsungInsuranceAdapter
from crawler.validators import DocumentClassifier
from tests.company_fixtures import company_definition


START, END = date(2026, 7, 1), date(2026, 7, 31)
CLASSIFIER = DocumentClassifier({"policy": ["약관"]}, [])


def _adapter(cls, code: str, mode: str = "new_or_revised"):
    return cls(
        company_definition(code, code),
        SimpleNamespace(date_selection_mode=mode, timeout=1),
        CLASSIFIER,
    )


def _active_row(source_id: str, name: str, start: str):
    return {
        "source_product_id": source_id,
        "product_name_normalized": name,
        "sale_start_date": start,
    }


def test_samsung_materializes_old_active_reference_from_same_json(monkeypatch):
    adapter = _adapter(SamsungInsuranceAdapter, "SAMSUNG")
    rows = [
        {"prdCode": "OLD", "prdName": "오래된 상품", "saleStDt": "20240101", "saleEnDt": "", "prdfilename1": "/old.pdf"},
        {"prdCode": "NEW", "prdName": "이번 상품", "saleStDt": "20260701", "saleEnDt": "", "prdfilename1": "/new.pdf"},
    ]
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        return rows

    monkeypatch.setattr(adapter, "_fetch_list", fetch)
    adapter.configure_active_status_refresh([_active_row("OLD", "오래된 상품", "2024-01-01")])

    versions = adapter.collect_product_versions(START, END)

    assert calls == 1
    assert [version.product_name_raw for version in versions] == ["오래된 상품", "이번 상품"]
    assert adapter.stats["status_coverage_complete"] is True


def test_samsung_failure_never_reports_complete(monkeypatch):
    adapter = _adapter(SamsungInsuranceAdapter, "SAMSUNG")
    adapter.configure_active_status_refresh([_active_row("OLD", "오래된 상품", "2024-01-01")])
    monkeypatch.setattr(adapter, "_fetch_list", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        adapter.collect_product_versions(START, END)
    assert adapter.stats["status_coverage_complete"] is False


def _mirae_row(seq: int, start: str, end: str = ""):
    return {
        "seq": seq,
        "jsonData": json.dumps(
            {
                "cell0": "건강",
                "cell1": f"상품-{seq}",
                "cell2": start,
                "cell3": end,
                "cell4": "summary.pdf",
                "cell5": "policy.pdf",
                "cell6": "method.pdf",
                "cell7": "/files",
            },
            ensure_ascii=False,
        ),
    }


class _Response:
    status_code = 200

    def __init__(self, rows):
        self.rows = rows

    def json(self):
        return {"list": self.rows}


def test_mirae_keeps_old_active_reference_and_completes_all_pages(monkeypatch):
    adapter = _adapter(MiraeLifeAdapter, "MIRAE_LIFE")
    calls = []

    def post(url, *, data, headers):
        calls.append((data["text1"], data["pageNum"]))
        return _Response([_mirae_row(7, "20240101")]) if data["pageNum"] == "0" else _Response([])

    adapter._client = SimpleNamespace(post=post)
    adapter.configure_active_status_refresh([_active_row("7", "상품-7", "2024-01-01")])

    versions = adapter.collect_product_versions(START, END)

    assert len(calls) == 4  # 두 탭 각각 page 0 + 종료 빈 페이지
    assert len(versions) == 2
    assert all(version.product_name_raw == "상품-7" for version in versions)
    assert adapter.stats["status_coverage_complete"] is True


def test_mirae_page_cap_marks_coverage_partial(monkeypatch):
    adapter = _adapter(MiraeLifeAdapter, "MIRAE_LIFE")
    adapter._client = SimpleNamespace(post=lambda *args, **kwargs: _Response([_mirae_row(7, "20240101")]))
    monkeypatch.setattr("crawler.adapters.mirae_life.MAX_PAGES", 1)

    adapter.collect_product_versions(START, END)

    assert adapter.stats["status_coverage_complete"] is False


def test_meritz_active_reference_uses_notf_tab_status(monkeypatch):
    adapter = _adapter(MeritzInsuranceAdapter, "MERITZ")
    monkeypatch.setattr(adapter, "open", lambda: None)
    list_calls = 0

    def call(service, body):
        nonlocal list_calls
        if service == "retrievePdList" and body.get("srtSq") == "1":
            list_calls += 1
            if list_calls % 2:
                return {"pdList": [{"srtSq": "1", "cdNm": "건강"}]}
            return {"pdDtlList": [{"srtSq": "1", "cmCommCd": "D"}]}
        if service == "retrievePdList":
            return {"pdDtlList": [{"srtSq": "1", "cmCommCd": "D"}]}
        return {"salPdList": [{
            "ntbdDtlSeq": "OLD",
            "ttlNm": "오래된 상품",
            "bgnDt": "20240101",
            "putupEdDdTm": "20240131",
            "putupStDdTm": "20240101",
        }]}

    monkeypatch.setattr(adapter, "_call", call)
    adapter.configure_active_status_refresh([_active_row("OLD", "오래된 상품", "2024-01-01")])

    versions = adapter.collect_product_versions(START, END)

    assert versions
    # 판매종료일이 있어도 raw notfYn=Y 탭의 상태를 보존한다.
    assert versions[0].sale_status == "판매중"
    assert versions[0].sale_end_date == date(2024, 1, 31)
    assert adapter.stats["status_coverage_complete"] is True


def test_lotte_marks_single_full_response_complete(monkeypatch):
    adapter = _adapter(LotteInsuranceAdapter, "LOTTE")
    monkeypatch.setattr(
        adapter,
        "_search",
        lambda _: '<script>document.getElementById("searchviewissale").innerHTML = "";</script>',
    )
    assert adapter.collect_product_versions(START, END) == []
    assert adapter.stats["status_coverage_complete"] is True
