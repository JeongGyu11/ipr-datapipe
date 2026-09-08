"""교보생명 JSON 상세 조회와 상품별 체크포인트 계약 테스트."""

from datetime import date
from types import SimpleNamespace

import pytest

import crawler.adapters.kyobo_life as kyobo_module
from crawler.adapters.kyobo_life import KyoboLifeAdapter
from crawler.http_client import AccessDeniedError
from tests.company_fixtures import company_definition


class Response:
    def __init__(self, payload=None, status_code=200, json_error=False):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._payload


class Client:
    def __init__(self, responses):
        self.responses = responses
        self.posts = []

    def post(self, url, **kwargs):
        body = kwargs.get("content", b"")
        import json

        payload = json.loads(body.decode("utf-8"))
        self.posts.append((url, payload))
        value = self.responses[payload["dgtPdtPdSeqtId"]]
        if isinstance(value, Exception):
            raise value
        return value


def product(seq="1", code="P1"):
    return {
        "dgtPdtAtrSeqtId": seq,
        "dgtPdtCd": code,
        "dgtPdtAtrNm": f"상품-{code}",
        "dgtPdtAtrMclCd": "M",
        "dgtPdtAtrSmclCd": "S",
        "saleYn": "Y",
    }


def adapter(client, checkpoint=None):
    instance = KyoboLifeAdapter.__new__(KyoboLifeAdapter)
    instance.code = "KYOBO_LIFE"
    instance.name = "교보생명"
    instance.company = company_definition("KYOBO_LIFE")
    instance.runtime_options = {}
    instance.stats = {}
    instance._active_status_rows = []
    instance.log = __import__("logging").getLogger("test-kyobo-life")
    instance.classifier = SimpleNamespace(
        is_excluded=lambda _value: False,
        classify=lambda label, _filename: label,
    )
    instance._client = client
    instance._fetch_products = lambda: [product("1", "P1"), product("2", "P2")]
    if checkpoint is not None:
        instance.configure_detail_checkpoint(str(checkpoint), "scope")
    return instance


def ok(periods=None, list2=None):
    return Response({"body": {"list": [] if periods is None else periods, "list2": list2}})


def test_success_and_failure_resume_only_retries_failed_product(tmp_path):
    client = Client({"1": ok([{"saleStDt": "20240101", "saleEdDt": ""}]), "2": Response(None, 500)})
    first = adapter(client, tmp_path)
    with pytest.raises(RuntimeError, match="1건"):
        first.collect_product_versions(date(2024, 1, 1), date(2024, 12, 31))
    assert first.stats["detail_checkpoint_attempted"] == 2

    client.responses["2"] = ok([])
    resumed = adapter(client, tmp_path)
    versions = resumed.collect_product_versions(date(2024, 1, 1), date(2024, 12, 31))
    assert len(versions) == 1
    assert [payload["dgtPdtPdSeqtId"] for _, payload in client.posts] == ["1", "2", "2"]
    assert resumed.stats["detail_checkpoint_reused"] == 1
    assert resumed.stats["detail_checkpoint_failed"] == 0


@pytest.mark.parametrize(
    "response",
    [Response({"body": {}}), Response({"body": {"list": {}}}), Response(None, 503), Response(None, json_error=True)],
)
def test_unreliable_detail_response_is_failure(tmp_path, response):
    client = Client({"1": response, "2": ok([])})
    instance = adapter(client, tmp_path)
    with pytest.raises(RuntimeError):
        instance.collect_product_versions(date(2024, 1, 1), date(2024, 12, 31))


def test_empty_list_is_valid_and_list2_is_optional(tmp_path):
    client = Client({"1": ok([]), "2": ok([])})
    instance = adapter(client, tmp_path)
    assert instance.collect_product_versions(date(2024, 1, 1), date(2024, 12, 31)) == []
    resumed = adapter(client, tmp_path)
    assert resumed.collect_product_versions(date(2024, 1, 1), date(2024, 12, 31)) == []
    assert len(client.posts) == 2


def test_period_and_three_document_mapping_survives_checkpoint_resume(tmp_path):
    periods = [{"saleStDt": "20240101", "saleEdDt": ""}]
    files = [{"temp01": "summary.pdf", "temp02": "policy.pdf", "temp03": "method.pdf"}]
    client = Client({"1": ok(periods, files)})
    first = adapter(client, tmp_path)
    first._fetch_products = lambda: [product("1", "P1")]
    versions = first.collect_product_versions(date(2024, 1, 1), date(2024, 12, 31))
    assert [(doc.document_label, doc.original_filename) for doc in versions[0].documents] == [
        ("상품요약서", "summary.pdf"),
        ("약관", "policy.pdf"),
        ("사업방법서", "method.pdf"),
    ]

    resumed = adapter(client, tmp_path)
    resumed._fetch_products = lambda: [product("1", "P1")]
    cached_versions = resumed.collect_product_versions(date(2024, 1, 1), date(2024, 12, 31))
    assert [(doc.document_label, doc.original_filename) for doc in cached_versions[0].documents] == [
        ("상품요약서", "summary.pdf"),
        ("약관", "policy.pdf"),
        ("사업방법서", "method.pdf"),
    ]
    assert len(client.posts) == 1


def test_missing_detail_sequence_is_failure_without_detail_post(tmp_path):
    instance = adapter(Client({"1": ok([]), "2": ok([])}), tmp_path)
    item = product("1", "P1")
    item["dgtPdtAtrSeqtId"] = ""
    instance._fetch_products = lambda: [item]
    with pytest.raises(RuntimeError):
        instance.collect_product_versions(date(2024, 1, 1), date(2024, 12, 31))
    assert instance._client.posts == []


def test_missing_product_code_uses_sequence_for_detail_and_source_id(tmp_path):
    client = Client({"1": ok([{"saleStDt": "20240101", "saleEdDt": "20241231"}])})
    instance = adapter(client, tmp_path)
    item = product("1", "")
    instance._fetch_products = lambda: [item]

    versions = instance.collect_product_versions(date(2024, 1, 1), date(2024, 12, 31))

    assert len(client.posts) == 1
    assert versions[0].source_product_id == "1"


def test_key_uses_both_normalized_identifiers():
    assert KyoboLifeAdapter._detail_key({"dgtPdtAtrSeqtId": " 1 ", "dgtPdtCd": " P1 "}) == "1|P1"


def test_access_denied_is_recorded_and_reraised(tmp_path):
    client = Client({"1": AccessDeniedError("blocked"), "2": ok([])})
    instance = adapter(client, tmp_path)
    with pytest.raises(AccessDeniedError):
        instance.collect_product_versions(date(2024, 1, 1), date(2024, 12, 31))


def test_http_403_detail_response_is_access_denied(tmp_path):
    client = Client({"1": Response(None, 403), "2": ok([])})
    instance = adapter(client, tmp_path)
    with pytest.raises(AccessDeniedError):
        instance.collect_product_versions(date(2024, 1, 1), date(2024, 12, 31))


def test_product_page_count_above_safety_limit_is_fatal(monkeypatch):
    instance = adapter(Client({}))
    del instance._fetch_products
    calls = []

    def fake_json_post(client, url, payload, *, referer):
        calls.append(payload["currentPage"])
        page = payload["currentPage"]
        return Response({"body": {"pageInfo": {"totPageCnt": 999}, "list": [product(str(page), f"P{page}")]}})

    monkeypatch.setattr(kyobo_module, "json_post", fake_json_post)
    monkeypatch.setattr(kyobo_module, "MAX_PAGES", 2)
    with pytest.raises(RuntimeError, match="안전 상한"):
        instance._fetch_products()
    assert calls == [1]


def test_product_page_count_zero_is_malformed(monkeypatch):
    instance = adapter(Client({}))
    del instance._fetch_products

    def fake_json_post(client, url, payload, *, referer):
        return Response({"body": {"pageInfo": {"totPageCnt": 0}, "list": []}})

    monkeypatch.setattr(kyobo_module, "json_post", fake_json_post)
    with pytest.raises(RuntimeError, match="양수가 아닙니다"):
        instance._fetch_products()


def test_conditional_stats_are_reset_on_reused_instance():
    instance = adapter(Client({}))
    instance.stats.update(
        coverage_capped=True,
        products_total=99,
        products_skipped=98,
        detail_checkpoint_attempted=7,
        detail_checkpoint_reused=6,
        detail_checkpoint_failed=5,
    )
    instance._fetch_products = lambda: []
    assert instance.collect_product_versions(date(2024, 1, 1), date(2024, 12, 31)) == []
    assert instance.stats["coverage_capped"] is False
    assert instance.stats["products_total"] == 0
    assert instance.stats["products_skipped"] == 0
    assert instance.stats["detail_checkpoint_attempted"] == 0
    assert instance.stats["detail_checkpoint_reused"] == 0
    assert instance.stats["detail_checkpoint_failed"] == 0


def test_product_pages_dedupe_identifier_pair_and_preserve_missing_identifier_rows(monkeypatch):
    instance = adapter(Client({"1": ok([]), "2": ok([])}))
    del instance._fetch_products
    missing_a = {"dgtPdtAtrNm": "누락-A"}
    missing_b = {"dgtPdtAtrNm": "누락-B"}
    page_rows = {
        1: [product("1", "P1"), missing_a],
        2: [product("1", "P1"), dict(missing_a), missing_b],
    }

    def fake_json_post(client, url, payload, *, referer):
        page = payload["currentPage"]
        return Response({"body": {"pageInfo": {"totPageCnt": 2}, "list": page_rows[page]}})

    monkeypatch.setattr("crawler.adapters.kyobo_life.json_post", fake_json_post)
    products = instance._fetch_products()

    assert [item.get("dgtPdtAtrNm") for item in products] == ["상품-P1", "누락-A", "누락-B"]
    assert instance.stats["products_raw"] == 5
    assert instance.stats["products_deduped"] == 3
    assert instance.stats["products_duplicates"] == 2
