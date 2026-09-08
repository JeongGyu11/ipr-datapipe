"""목록 API 장애를 빈 성공으로 삼키지 않는 계약 테스트."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

import crawler.adapters.kyobo_life as kyobo_module
from crawler.adapters.db_insurance import DBInsuranceAdapter, STEP4, STEP5
from crawler.adapters.db_life import DBLifeAdapter
from crawler.adapters.kyobo_life import KyoboLifeAdapter
from crawler.adapters.lotte_insurance import LotteInsuranceAdapter
from crawler.adapters.meritz_insurance import MeritzInsuranceAdapter
from crawler.adapters.mirae_life import MiraeLifeAdapter
from crawler.adapters.samsung_insurance import SamsungInsuranceAdapter
from crawler.http_client import AccessDeniedError
from crawler.validators import DocumentClassifier
from tests.company_fixtures import company_definition


class Response:
    def __init__(self, payload=None, status_code=200, *, json_error=False, text=""):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error
        self.text = text
        self.content = text.encode()
        self.headers = {}

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._payload


class Client:
    def __init__(self, response):
        self.response = response

    def post(self, *args, **kwargs):
        return self.response

    def get(self, *args, **kwargs):
        return self.response


def _base(adapter_cls, code):
    adapter = adapter_cls.__new__(adapter_cls)
    adapter.code = code
    adapter.name = code
    adapter.base_url = "https://example.test"
    adapter.config = SimpleNamespace(timeout=1, date_selection_mode="new_or_revised")
    adapter.company = company_definition(code)
    adapter.runtime_options = {}
    adapter.log = __import__("logging").getLogger("list-contract")
    adapter.classifier = DocumentClassifier({"policy": ["약관"], "summary": ["요약"], "method": ["방법"]}, [])
    adapter.stats = {}
    adapter._active_status_rows = []
    return adapter


def test_db_step5_missing_result_raises_and_step4_failure_stays_ongoing():
    adapter = _base(DBInsuranceAdapter, "DB")
    adapter._client = Client(Response({}))
    with pytest.raises(RuntimeError):
        adapter.collect_product_versions(date(2026, 1, 1), date(2026, 1, 31))

    adapter._client = Client(Response({"result": []}))
    assert adapter.collect_product_versions(date(2026, 1, 1), date(2026, 1, 31)) == []

    row = {"SQNO": "1", "PDC_NM": "상품", "SALE_BEGIN_DAY": "20260101", "ARC_PDC_SL_YN": "1"}
    class Step4Client(Client):
        def post(self, url, **kwargs):
            if url.endswith(STEP5):
                return Response({"result": [row]})
            return Response({})
    adapter._client = Step4Client(None)
    versions = adapter.collect_product_versions(date(2026, 1, 1), date(2026, 1, 31))
    assert len(versions) == 1 and adapter.stats["step4_failed"] == 1


def test_db_step4_access_denied_is_reraised():
    adapter = _base(DBInsuranceAdapter, "DB")
    row = {"SQNO": "1", "PDC_NM": "상품", "SALE_BEGIN_DAY": "20260101", "ARC_PDC_SL_YN": "1"}

    class Step4DeniedClient(Client):
        def post(self, url, **kwargs):
            if url.endswith(STEP5):
                return Response({"result": [row]})
            assert url.endswith(STEP4)
            return Response(None, 403)

    adapter._client = Step4DeniedClient(None)
    with pytest.raises(AccessDeniedError):
        adapter.collect_product_versions(date(2026, 1, 1), date(2026, 1, 31))


@pytest.mark.parametrize("response", [Response(None, 500), Response(None, json_error=True), Response({"responseMessage": {"body": {"result": "F", "data": {"list": []}}}})])
def test_samsung_list_failures_raise(response):
    adapter = _base(SamsungInsuranceAdapter, "SAMSUNG")
    adapter._client = Client(response)
    with pytest.raises(RuntimeError):
        adapter._fetch_list()


def test_samsung_explicit_empty_list_is_success():
    adapter = _base(SamsungInsuranceAdapter, "SAMSUNG")
    adapter._client = Client(Response({"responseMessage": {"body": {"result": "S", "data": {"list": []}}}}))
    assert adapter._fetch_list() == []


@pytest.mark.parametrize("response", [Response(None, 500), Response(None, json_error=True), Response({})])
def test_mirae_page_failures_raise(response):
    adapter = _base(MiraeLifeAdapter, "MIRAE_LIFE")
    adapter._client = Client(response)
    with pytest.raises(RuntimeError):
        adapter._collect("판매중인상품", "판매중", date(2026, 1, 1), date(2026, 1, 31))


def test_mirae_explicit_empty_list_is_success():
    adapter = _base(MiraeLifeAdapter, "MIRAE_LIFE")
    adapter._client = Client(Response({"list": []}))
    assert adapter._collect("판매중인상품", "판매중") == []


@pytest.mark.parametrize("response", [Response(None, 500), Response(None, json_error=True), Response({"body": {"list": []}})])
def test_kyobo_list_failures_raise(monkeypatch, response):
    adapter = _base(KyoboLifeAdapter, "KYOBO_LIFE")
    adapter._client = Client(response)
    monkeypatch.setattr(kyobo_module, "json_post", lambda *args, **kwargs: response)
    with pytest.raises(RuntimeError):
        adapter._fetch_products()


def test_kyobo_explicit_empty_list_is_success(monkeypatch):
    response = Response({"body": {"pageInfo": {"totPageCnt": 1}, "list": []}})
    adapter = _base(KyoboLifeAdapter, "KYOBO_LIFE")
    adapter._client = Client(response)
    monkeypatch.setattr(kyobo_module, "json_post", lambda *args, **kwargs: response)
    assert adapter._fetch_products() == []


def test_db_life_http_failure_raises_and_empty_html_succeeds():
    adapter = _base(DBLifeAdapter, "DB_LIFE")
    adapter._client = Client(Response(None, 500))
    with pytest.raises(RuntimeError):
        adapter._collect("sale", "판매중", "1", "개인상품")
    adapter._client = Client(Response(None, text="<html><body><table><tr><th>헤더</th></tr></table></body></html>"))
    assert adapter._collect("sale", "판매중", "1", "개인상품") == []


def test_meritz_required_lists_reject_missing_and_accept_empty():
    assert MeritzInsuranceAdapter._required_list({"salPdList": []}, "salPdList", "retrieveSalPdList") == []
    with pytest.raises(RuntimeError):
        MeritzInsuranceAdapter._required_list({}, "salPdList", "retrieveSalPdList")


def test_lotte_http_failure_and_malformed_raise_but_empty_view_is_success():
    adapter = _base(LotteInsuranceAdapter, "LOTTE")
    adapter._client = Client(Response(None, 500))
    with pytest.raises(RuntimeError):
        adapter.collect_product_versions(date(2026, 1, 1), date(2026, 1, 31))
    adapter._client = Client(Response(None, text=""))
    with pytest.raises(RuntimeError):
        adapter.collect_product_versions(date(2026, 1, 1), date(2026, 1, 31))
    adapter._client = Client(
        Response(
            None,
            text='<script>document.getElementById("searchviewissale").innerHTML = "";</script>'
        )
    )
    assert adapter.collect_product_versions(date(2026, 1, 1), date(2026, 1, 31)) == []
