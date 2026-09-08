"""DB생명 판매중지 AJAX 상세 계약 테스트."""

from datetime import date
from types import SimpleNamespace

import pytest

from crawler.adapters.db_life import DBLifeAdapter, LIST_PATH, SOLD_OUT_DETAIL_URL
from crawler.http_client import AccessDeniedError
from models.document import DocumentType
from crawler.validators import DocumentClassifier
from tests.company_fixtures import company_definition


class Response:
    def __init__(self, text: str = "", status_code: int = 200):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"content-type": "application/xml; charset=utf-8"}


class Client:
    def __init__(self, listing: str, details: dict[str, Response] | None = None):
        self.listing = listing
        self.details = details or {}
        self.posts: list[tuple[str, dict, dict]] = []

    def get(self, *_args, **_kwargs):
        return Response(self.listing)

    def post(self, url, *, data=None, headers=None, **_kwargs):
        self.posts.append((url, data or {}, headers or {}))
        return self.details.get(data["mcode"], Response("<root/>"))


def adapter(client, checkpoint=None):
    a = DBLifeAdapter.__new__(DBLifeAdapter)
    a.code = "DB_LIFE"
    a.name = "DB생명"
    a.base_url = LIST_PATH["sale"]
    a.classifier = DocumentClassifier(
        {"policy": ["약관"], "summary": ["요약서"], "method": ["방법서"]}, []
    )
    a.company = company_definition("DB_LIFE")
    a.runtime_options = {}
    a.stats = {}
    a._active_status_rows = []
    a.log = __import__("logging").getLogger("test-db-life")
    a._client = client
    if checkpoint is not None:
        a.configure_detail_checkpoint(str(checkpoint), "20240101_20260820")
    return a


LISTING = """
<html><head>
  <meta name="_csrf_header" content="X-CSRF-TOKEN">
  <meta name="_csrf" content="test-token">
</head><body>
  <a class="mctg" name="mcode" data-value="B001001">보장성보험</a>
  <a class="mctg" name="mcode" data-value="B001001">보장성보험</a>
  <a class="mctg" name="mcode" data-value="B001002">저축보험</a>
</body></html>
"""


def detail(name="테스트보험", publish="1001", start="20240101", end="20241231"):
    return f"""<root><poplist>
      <MAIN_CTG>보장</MAIN_CTG><PRODUCT_NAME>{name}</PRODUCT_NAME>
      <SALE_START_DATE>{start}</SALE_START_DATE><SALE_END_DATE>{end}</SALE_END_DATE>
      <FILE1_NAME>{name}_방법서.pdf</FILE1_NAME><FILE3_NAME>{name}_약관.zip</FILE3_NAME>
      <PUBLISH_NO>{publish}</PUBLISH_NO>
    </poplist></root>"""


def test_sold_out_refs_are_deduplicated_and_ajax_contract_is_exact():
    client = Client(LISTING, {
        "B001001": Response(detail()),
        "B001002": Response("<root/>") ,
    })
    a = adapter(client)
    versions = a._collect("sold_out", "판매중지", "1", "개인상품")

    assert len(client.posts) == 2
    url, body, headers = client.posts[0]
    assert url == SOLD_OUT_DETAIL_URL
    assert body == {"mcode": "B001001", "gubn1": "1"}
    assert headers["X-Requested-With"] == "XMLHttpRequest"
    assert headers["Referer"] == LIST_PATH["sold_out"]
    assert headers["X-CSRF-TOKEN"] == "test-token"
    assert headers["Content-Type"] == "application/x-www-form-urlencoded; charset=UTF-8"
    assert len(versions) == 1
    version = versions[0]
    assert version.sale_status == "판매중지"
    assert version.sale_start_date == date(2024, 1, 1)
    assert version.sale_end_date == date(2024, 12, 31)
    assert version.source_product_id == "1001"
    assert version.documents[0].document_type == DocumentType.METHOD
    assert version.documents[0].document_url.endswith("/file/1001/1")
    assert version.extra["provUrl"].endswith("/prov/soldOut/1001")


def test_namespaced_xml_and_multiple_poplist_versions_are_mapped():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <ns:root xmlns:ns="urn:test"><ns:poplist>
      <ns:MAIN_CTG>A</ns:MAIN_CTG><ns:PRODUCT_NAME>첫상품</ns:PRODUCT_NAME>
      <ns:SALE_START_DATE>20240101</ns:SALE_START_DATE><ns:SALE_END_DATE>20241231</ns:SALE_END_DATE>
      <ns:FILE1_NAME>첫방법서.pdf</ns:FILE1_NAME><ns:PUBLISH_NO>p1</ns:PUBLISH_NO>
    </ns:poplist><ns:poplist>
      <ns:MAIN_CTG>B</ns:MAIN_CTG><ns:PRODUCT_NAME>둘상품</ns:PRODUCT_NAME>
      <ns:SALE_START_DATE>20250101</ns:SALE_START_DATE><ns:SALE_END_DATE>20251231</ns:SALE_END_DATE>
      <ns:FILE3_NAME>둘약관.zip</ns:FILE3_NAME><ns:PUBLISH_NO>p2</ns:PUBLISH_NO>
    </ns:poplist></ns:root>"""
    a = adapter(Client(LISTING, {"B001001": Response(xml), "B001002": Response("<root/>")}))
    versions = a._collect("sold_out", "판매중지", "1", "개인상품")
    assert [(v.product_name_raw, v.source_product_id) for v in versions] == [("첫상품", "p1"), ("둘상품", "p2")]
    assert versions[0].documents[0].document_type == DocumentType.METHOD
    assert versions[1].documents == []
    assert versions[1].extra["provUrl"].endswith("/prov/soldOut/p2")


def test_empty_poplist_is_success_and_reused(tmp_path):
    client = Client(LISTING, {"B001001": Response("<root/>"), "B001002": Response("<root/>")})
    a = adapter(client, tmp_path)
    assert a._collect("sold_out", "판매중지", "1", "개인상품") == []
    assert len(client.posts) == 2

    resumed = adapter(client, tmp_path)
    assert resumed._collect("sold_out", "판매중지", "1", "개인상품") == []
    assert len(client.posts) == 2
    assert resumed.stats["detail_checkpoint_reused"] == 2


def test_failed_detail_is_recorded_and_only_failed_ref_retries(tmp_path):
    client = Client(LISTING, {
        "B001001": Response("<root><poplist><PRODUCT_NAME>A</PRODUCT_NAME><PUBLISH_NO>1</PUBLISH_NO></poplist></root>"),
        "B001002": Response("broken"),
    })
    a = adapter(client, tmp_path)
    assert len(a._collect("sold_out", "판매중지", "1", "개인상품")) == 1
    assert a.stats["failed"] == 1
    assert len(client.posts) == 2

    client.details["B001002"] = Response(detail("B", "2"))
    resumed = adapter(client, tmp_path)
    versions = resumed._collect("sold_out", "판매중지", "1", "개인상품")
    assert [v.source_product_id for v in versions] == ["1", "2"]
    assert [p[1]["mcode"] for p in client.posts] == ["B001001", "B001002", "B001002"]


def test_http_and_malformed_are_fatal_but_access_denied_is_reraised(tmp_path):
    client = Client(LISTING, {"B001001": Response("error", 500), "B001002": Response("broken")})
    a = adapter(client, tmp_path)
    assert a._collect("sold_out", "판매중지", "1", "개인상품") == []
    assert a.stats["failed"] == 2

    class Denied(Client):
        def post(self, *args, **kwargs):
            raise AccessDeniedError("blocked")

    denied = adapter(Denied(LISTING), tmp_path)
    with pytest.raises(AccessDeniedError):
        denied._collect("sold_out", "판매중지", "1", "개인상품")

    denied_company = adapter(Denied(LISTING), tmp_path)
    with pytest.raises(AccessDeniedError):
        denied_company.collect_product_versions(date(2024, 1, 1), date(2026, 8, 20))


def test_http_403_detail_response_is_access_denied(tmp_path):
    client = Client(LISTING, {"B001001": Response("blocked", 403)})
    with pytest.raises(AccessDeniedError):
        adapter(client, tmp_path)._collect("sold_out", "판매중지", "1", "개인상품")


def test_sale_static_row_parser_regression():
    html = """<table><tbody><tr>
      <th>보장</th><th>건강</th><th>판매보험</th>
      <td>2024.01.01 ~</td><td><a href="/notice/product/file/9/1">방법서.pdf</a></td>
      <td><a href="/notice/product/file/9/2">요약서.pdf</a></td>
      <td><a href="/notice/product/prov/sale/9">약관</a></td>
    </tr></tbody></table>"""
    a = adapter(Client(html))
    versions = a._collect("sale", "판매중", "1", "개인상품")
    assert len(versions) == 1
    assert versions[0].product_name_raw == "판매보험"
    assert len(versions[0].documents) == 2
    assert versions[0].extra["provUrl"].endswith("/prov/sale/9")


def test_collection_stats_are_reset_when_adapter_instance_is_reused():
    a = adapter(Client("<html/>"))
    a.stats.update(failed=3, attempted=5, detail_checkpoint_failed=3)

    assert a.collect_product_versions(date(2024, 1, 1), date(2024, 1, 31)) == []

    assert a.stats["failed"] == 0
    assert a.stats["attempted"] == 0
    assert a.stats["detail_checkpoint_failed"] == 0
