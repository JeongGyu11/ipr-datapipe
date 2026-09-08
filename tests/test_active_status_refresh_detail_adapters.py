"""상태 재검증을 수행하는 상세 어댑터의 네트워크 호출 계약 테스트."""

from datetime import date
from types import SimpleNamespace

import pytest

from crawler.adapters.db_insurance import DBInsuranceAdapter, STEP4
import crawler.adapters.db_life as db_life_module
from crawler.adapters.db_life import DBLifeAdapter
from crawler.adapters.kb_insurance import KBInsuranceAdapter
from crawler.adapters.kyobo_life import KyoboLifeAdapter
from crawler.detail_checkpoint_service import DetailCheckpoint
from crawler.http_client import AccessDeniedError
from crawler.validators import DocumentClassifier
from models.product_version import ProductVersion
from tests.company_fixtures import company_definition


CLASSIFIER = DocumentClassifier({"policy": ["약관"], "summary": ["요약"], "method": ["방법"]}, [])
START, END = date(2026, 7, 1), date(2026, 7, 31)


def _base(adapter):
    adapter.company = company_definition(adapter.__class__.code)
    adapter.runtime_options = {}
    adapter.code = adapter.__class__.code
    adapter.name = adapter.__class__.code
    adapter.base_url = "https://example.test"
    adapter.classifier = CLASSIFIER
    adapter.stats = {}
    adapter.log = __import__("logging").getLogger("active-refresh-test")
    adapter._active_status_rows = []
    return adapter


def _active(source_id="OLD", name="오래된 상품", start="2024-01-01"):
    return {"source_product_id": source_id, "product_name_normalized": name, "sale_start_date": start}


def test_db_old_active_is_step4_refreshed_once_and_access_denied_is_fatal():
    adapter = _base(DBInsuranceAdapter.__new__(DBInsuranceAdapter))
    adapter.config = SimpleNamespace(date_selection_mode="new_or_revised")
    calls = []

    def post(path, payload):
        calls.append((path, payload))
        return {"result": [{"SL_STR_DT": "20240101", "SL_FIN_DT": "20260715"}]}

    adapter._search = lambda *_: []
    adapter._post_json = post
    adapter.configure_active_status_refresh([_active()])
    versions = adapter.collect_product_versions(START, END)
    assert len(versions) == 1
    assert versions[0].source_product_id == "OLD"
    assert versions[0].sale_start_date == date(2024, 1, 1)
    assert versions[0].sale_status == "판매중지"
    assert [item for item in calls if item[0] == STEP4] == [(STEP4, {"sqno": "OLD", "arc_pdc_sl_yn": "1"})]
    assert adapter.stats["status_coverage_complete"] is True

    denied = _base(DBInsuranceAdapter.__new__(DBInsuranceAdapter))
    denied.config = SimpleNamespace(date_selection_mode="new_or_revised")
    denied._search = lambda *_: []
    denied._post_json = lambda *_: (_ for _ in ()).throw(AccessDeniedError("blocked"))
    denied.configure_active_status_refresh([_active()])
    with pytest.raises(AccessDeniedError):
        denied.collect_product_versions(START, END)


def test_db_failed_step4_keeps_active_and_marks_partial():
    adapter = _base(DBInsuranceAdapter.__new__(DBInsuranceAdapter))
    adapter.config = SimpleNamespace(date_selection_mode="new_or_revised")
    adapter._search = lambda *_: []
    adapter._post_json = lambda *_: {}
    adapter.configure_active_status_refresh([_active()])
    versions = adapter.collect_product_versions(START, END)
    assert versions[0].sale_status == "판매중"
    assert versions[0].sale_end_date is None
    assert adapter.stats["status_coverage_complete"] is False


class _Checkpoint:
    def __init__(self, cached):
        self.cached = cached
        self.reused_keys = []
        self.saved = []
        self.path = "checkpoint"

    def reusable(self, product):
        key = str(
            product.get("product_code")
            or product.get("dgtPdtCd")
            or f"{product.get('gubn1')}|{product.get('mcode')}"
        )
        self.reused_keys.append(key)
        return self.cached.get(key)

    def record_success(self, product, versions):
        self.saved.append((product, versions))

    def record_failure(self, *_):
        pass


def test_kb_active_bypasses_checkpoint_non_active_reuses_and_cap_is_partial():
    adapter = _base(KBInsuranceAdapter.__new__(KBInsuranceAdapter))
    products = [
        {"product_code": "OLD", "product_name": "오래된 상품", "category": "건강", "bojong_no": "1", "gubun": "A", "bojong_seq": "1"},
        {"product_code": "NEW", "product_name": "새 상품", "category": "건강", "bojong_no": "2", "gubun": "A", "bojong_seq": "1"},
    ]
    cached = {
        "NEW": DetailCheckpoint(key="new", status="completed", versions=[]),
    }
    checkpoint = _Checkpoint(cached)
    adapter._checkpoint_service = lambda: checkpoint
    adapter._collect_products = lambda limit=None: (products[:limit] if limit else products, 2)
    detail_calls = []
    adapter._collect_versions_with_status = lambda product: (detail_calls.append(product["product_code"]) or ([], True))
    adapter.configure_active_status_refresh([_active("1|A|1", "오래된 상품")])
    adapter.collect_product_versions(START, END)
    assert detail_calls == ["OLD"]
    assert checkpoint.reused_keys == ["NEW"]
    assert adapter.stats["status_coverage_complete"] is True

    capped = _base(KBInsuranceAdapter.__new__(KBInsuranceAdapter))
    capped.runtime_options = {"max_products": 1}
    capped._checkpoint_service = lambda: None
    capped._collect_products = lambda limit=None: (products[:limit], 2)
    capped._collect_versions_with_status = lambda product: ([], True)
    capped.collect_product_versions(START, END)
    assert capped.stats["status_coverage_complete"] is False


def test_kyobo_active_bypasses_checkpoint_and_max_products_is_partial():
    adapter = _base(KyoboLifeAdapter.__new__(KyoboLifeAdapter))
    products = [
        {"dgtPdtAtrSeqtId": "1", "dgtPdtCd": "OLD", "dgtPdtAtrNm": "오래된 상품", "saleYn": "Y"},
        {"dgtPdtAtrSeqtId": "2", "dgtPdtCd": "NEW", "dgtPdtAtrNm": "새 상품", "saleYn": "Y"},
    ]
    checkpoint = _Checkpoint({"NEW": DetailCheckpoint(key="new", status="completed", versions=[])})
    adapter._checkpoint_service = lambda: checkpoint
    adapter._fetch_products = lambda: products
    calls = []
    adapter._fetch_versions = lambda product: calls.append(product["dgtPdtCd"]) or []
    adapter.configure_active_status_refresh([_active("OLD", "오래된 상품")])
    adapter.collect_product_versions(START, END)
    assert calls == ["OLD"]
    assert checkpoint.reused_keys == ["NEW"]
    assert adapter.stats["status_coverage_complete"] is True

    capped = _base(KyoboLifeAdapter.__new__(KyoboLifeAdapter))
    capped.runtime_options = {"max_products": 1}
    capped._checkpoint_service = lambda: None
    capped._fetch_products = lambda: products
    capped._fetch_versions = lambda product: []
    capped.collect_product_versions(START, END)
    assert capped.stats["status_coverage_complete"] is False


def test_db_life_active_cached_sold_out_is_forced_fresh_and_page_cap_is_partial(monkeypatch):
    adapter = _base(DBLifeAdapter.__new__(DBLifeAdapter))
    active_version = ProductVersion(
        company_code="DB_LIFE", company_name="DB생명", product_name_raw="오래된 상품",
        source_page_url="https://example.test", source_product_id="P1",
        sale_start_date=date(2024, 1, 1), sale_status="판매중",
    )
    checkpoint = _Checkpoint({"1|M1": DetailCheckpoint(key="1|M1", status="completed", versions=[active_version])})
    adapter._detail_checkpoint = checkpoint
    adapter._checkpoint_service = lambda: checkpoint
    adapter._parse_sold_out_refs = lambda *_: [{"mcode": "M1", "gubn1": "1", "category": "건강", "list_name": "오래된 상품"}]
    fresh_calls = []
    adapter._fetch_sold_out_detail = lambda product, channel: (fresh_calls.append(product["mcode"]) or [])
    adapter.configure_active_status_refresh([_active("P1", "오래된 상품")])
    adapter._collect_sold_out_page(SimpleNamespace(), "1", "개인상품", set())
    assert fresh_calls == ["M1"]
    assert checkpoint.reused_keys == ["1|M1"]

    monkeypatch.setattr(db_life_module, "MAX_PAGES", 1)
    capped = _base(DBLifeAdapter.__new__(DBLifeAdapter))
    capped._client = SimpleNamespace(get=lambda *args, **kwargs: SimpleNamespace(
        status_code=200, text='<div data-total-page="2"></div><table></table>'
    ))
    capped._collect("sale", "판매중", "1", "개인상품")
    assert capped.stats["status_coverage_complete"] is False
