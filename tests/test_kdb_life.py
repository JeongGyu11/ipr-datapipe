from __future__ import annotations

import json
from types import SimpleNamespace

from crawler.adapters.kdb_life import KDBLifeAdapter
from crawler.validators import DocumentClassifier
from models.document import DocumentType
from tests.company_fixtures import company_definition


class Response:
    status_code = 200

    def __init__(self, payload):
        self.content = json.dumps(payload, ensure_ascii=False).encode("euc-kr")
        self.headers = {"content-type": "application/json; charset=euc-kr"}


class DetailClient:
    def post(self, url, **kwargs):
        assert "scrId=HDLMA002P01P" in url
        assert "productIdx" in kwargs["content"]
        return Response(
            {
                "resultList": [
                    {
                        "PRODUCT_NAME": "테스트상품",
                        "SALE_START_DATE": "20240401",
                        "SALE_END_DATE": "20250331",
                        "AGREEMENT": "/files/policy.pdf",
                        "PRODUCT_SUMMARY": "/files/method.pdf",
                        "PRODUCT_GUIDE": "/files/summary.pdf",
                    }
                ]
            }
        )


def test_sold_out_detail_expands_period_rows_and_documents():
    adapter = KDBLifeAdapter.__new__(KDBLifeAdapter)
    adapter.code = "KDB_LIFE"
    adapter.name = "KDB생명"
    adapter.company = company_definition("KDB_LIFE")
    adapter.config = SimpleNamespace(timeout=1, date_selection_mode="new_or_revised")
    adapter.runtime_options = {}
    adapter.log = __import__("logging").getLogger("kdb-life-test")
    adapter.classifier = DocumentClassifier(
        {"policy": ["약관"], "summary": ["요약"], "method": ["방법"]}, []
    )
    adapter.stats = {}
    adapter._active_status_rows = []
    adapter._client = DetailClient()

    versions = adapter._collect_sold_out_details(
        {
            "PRODUCT_IDX": 774,
            "P_CATEGORY_GROUP": 2,
            "P_CATEGORY_NAME": "제도성특약",
            "PRODUCT_NAME": "테스트상품",
        },
        "제도성특약",
        "FC/GA보험",
        "판매중지",
    )

    assert len(versions) == 1
    version = versions[0]
    assert version.source_product_id == "774"
    assert version.sale_start_date.isoformat() == "2024-04-01"
    assert version.sale_end_date.isoformat() == "2025-03-31"
    assert version.sale_status == "판매중지"
    assert {doc.document_type for doc in version.documents} == {
        DocumentType.POLICY,
        DocumentType.SUMMARY,
        DocumentType.METHOD,
    }
