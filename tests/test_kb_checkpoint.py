"""KB 상품 상세 체크포인트의 내구성·재개 동작 테스트."""

from datetime import date
import logging

import pytest

from crawler.adapters.kb_insurance import KBInsuranceAdapter
from crawler.kb_checkpoint_service import KBCheckpointService, product_key
from models.document import Document, DocumentType
from models.product_version import ProductVersion
from tests.company_fixtures import company_definition


def _product(code="001"):
    return {
        "product_code": code,
        "product_name": f"테스트상품{code}",
        "bojong_no": code,
        "gubun": "A",
        "bojong_seq": "1",
        "category": "건강보험",
    }


def _version(product_id="001"):
    return ProductVersion(
        company_code="KB",
        company_name="KB손해보험",
        storage_name=company_definition("KB").storage_name,
        product_name_raw="테스트상품",
        product_category="건강보험",
        source_product_id=product_id,
        source_page_url="https://example.test/detail",
        version_key="20240101_판매개시",
        sale_status="판매중",
        sale_start_date=date(2024, 1, 1),
        extra={"detail": {"bojongNo": product_id}},
        documents=[Document(
            document_type=DocumentType.POLICY,
            document_label="약관",
            document_url="https://example.test/policy.pdf",
            original_filename="약관.pdf",
            download_hint={"source": "kb"},
        )],
    )


def test_checkpoint_round_trip_and_scope_isolation(tmp_path):
    product = _product()
    service = KBCheckpointService(tmp_path, scope="20240101_20260820")
    service.record_success(product, [_version()])

    resumed = KBCheckpointService(tmp_path, scope="20240101_20260820")
    checkpoint = resumed.reusable(product)
    assert checkpoint is not None
    assert checkpoint.versions[0].sale_start_date == date(2024, 1, 1)
    assert checkpoint.versions[0].documents[0].download_hint == {"source": "kb"}

    # 같은 상품이라도 scope가 다르면 새로운 백필로 취급한다.
    assert KBCheckpointService(tmp_path, scope="20250101_20260820").get(product) is None


def test_failed_checkpoint_is_not_reused_and_success_replaces_it(tmp_path):
    product = _product()
    service = KBCheckpointService(tmp_path, scope="scope")
    service.record_failure(product, "HTTP 503")
    assert service.get(product).completed is False
    assert service.reusable(product) is None

    service.record_success(product, [])
    assert service.reusable(product).completed is True
    assert service.reusable(product).versions == []


def test_truncated_tail_is_ignored_and_previous_success_survives(tmp_path):
    product = _product()
    service = KBCheckpointService(tmp_path, scope="scope")
    service.record_success(product, [_version()])
    service.path.write_text(
        service.path.read_text(encoding="utf-8") + '{"key":"broken"',
        encoding="utf-8",
    )

    resumed = KBCheckpointService(tmp_path, scope="scope")
    assert resumed.reusable(product) is not None
    assert resumed.completed_count() == 1


def test_product_key_uses_all_kb_identifiers():
    assert product_key(_product("001")) != product_key({**_product("001"), "gubun": "B"})
    assert product_key(_product("001")) == product_key({
        "bojongNo": "001", "gubun": "A", "bojongSeq": "1",
    })


class _Response:
    status_code = 200

    def __init__(self, text):
        self.text = text


class _Client:
    def __init__(self, text):
        self.text = text

    def post(self, *_args, **_kwargs):
        return _Response(self.text)


def _adapter_with_detail(html: str) -> KBInsuranceAdapter:
    adapter = KBInsuranceAdapter.__new__(KBInsuranceAdapter)
    adapter._active_status_rows = []
    adapter._client = _Client(html)
    adapter.log = logging.getLogger("test-kb")
    adapter.code = "KB"
    adapter.name = "KB손해보험"
    adapter.base_url = "https://example.test"
    adapter.company = company_definition("KB")
    adapter.runtime_options = {}
    return adapter


def test_empty_detail_is_not_complete_and_bad_date_is_preserved_for_review():
    empty = _adapter_with_detail("<table class='tb_view'><tr><th>상품</th></tr></table>")
    versions, complete = empty._collect_versions_with_status(_product())
    assert versions == []
    assert complete is False

    partial = _adapter_with_detail("""
        <table class='tb_view'><table>
          <tr><td>2024-01-01</td><td></td><td></td><td></td><td></td></tr>
          <tr><td>날짜오류</td><td></td><td></td><td></td><td></td></tr>
        </table></table>
    """)
    versions, complete = partial._collect_versions_with_status(_product())
    assert len(versions) == 2
    assert complete is True
    assert versions[0].source_product_id == "001|A|1"
    assert versions[1].sale_start_date is None
    assert versions[1].version_key.startswith("날짜미상_")


def test_three_column_retirement_detail_is_complete_and_normalizes_blank_code():
    retirement = _adapter_with_detail("""
        <table class='tb_view'><table>
          <tr><td>2024-04-01</td><td>2024-12-12</td><td></td></tr>
          <tr><td>2024-12-13</td><td></td><td></td></tr>
        </table></table>
    """)
    item = {**_product(""), "bojong_no": "     ", "gubun": "7", "bojong_seq": "8"}

    versions, complete = retirement._collect_versions_with_status(item)

    assert complete is True
    assert len(versions) == 2
    assert {version.source_product_id for version in versions} == {"|7|8"}


def test_detail_failure_fails_collection_but_keeps_retry_semantics(monkeypatch):
    adapter = KBInsuranceAdapter.__new__(KBInsuranceAdapter)
    adapter.company = company_definition("KB")
    adapter.runtime_options = {}
    adapter.stats = {}
    adapter._active_status_rows = []
    adapter.log = logging.getLogger("test-kb")
    monkeypatch.setattr(adapter, "_collect_products", lambda limit=None: ([_product()], 1))
    monkeypatch.setattr(adapter, "_checkpoint_service", lambda: None)
    monkeypatch.setattr(adapter, "_collect_versions_with_status", lambda product: ([], False))

    with pytest.raises(RuntimeError, match="상세 1건"):
        adapter.collect_product_versions(date(2024, 1, 1), date(2026, 1, 1))


def test_list_http_failure_is_not_returned_as_partial_success():
    adapter = _adapter_with_detail("")
    adapter._client = type("FailClient", (), {
        "post": lambda self, *args, **kwargs: type("R", (), {"status_code": 503, "text": ""})()
    })()
    with pytest.raises(RuntimeError, match="목록 조회 실패"):
        adapter._collect_products()
