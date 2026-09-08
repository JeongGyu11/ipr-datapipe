"""미래에셋생명 문서 다운로드 AJAX 요청 계약 테스트."""

from types import SimpleNamespace

from crawler.adapters.mirae_life import AJAX_HEADERS, MiraeLifeAdapter
from crawler.validators import DocumentClassifier
from models.document import Document
from tests.company_fixtures import company_definition


class _Client:
    def __init__(self):
        self.calls = []

    def post(self, url, *, data, headers):
        self.calls.append((url, data, headers))
        raise AssertionError("문서 셀 분할 테스트에서는 네트워크 호출을 하지 않아야 합니다")


class _DownloadResponse:
    status_code = 200
    content = b"%PDF-1.7\nfixture"
    headers = {"content-type": "application/pdf"}


class _DownloadClient:
    def __init__(self):
        self.calls = []

    def post(self, url, *, data, headers):
        self.calls.append((url, data, headers))
        return _DownloadResponse()


def _adapter(client):
    adapter = MiraeLifeAdapter.__new__(MiraeLifeAdapter)
    adapter.code = "MIRAE_LIFE"
    adapter.name = "미래에셋생명"
    adapter.base_url = "https://example.test"
    adapter.company = company_definition("MIRAE_LIFE")
    adapter.runtime_options = {}
    adapter.config = SimpleNamespace(timeout=1, date_selection_mode="new_or_revised")
    adapter.classifier = DocumentClassifier({"policy": ["약관"]}, [])
    adapter.log = __import__("logging").getLogger("mirae-download-contract")
    adapter._active_status_rows = []
    adapter._client = client
    return adapter


def test_download_uses_required_ajax_headers():
    client = _DownloadClient()
    adapter = _adapter(client)
    document = Document(
        document_type="POLICY",
        document_label="약관",
        original_filename="fixture.pdf",
        download_hint={
            "filePath": "/uploadwas/life/html/gongci/upload/1/",
            "fileName": "fixture.pdf",
        },
    )

    result = adapter.fetch_document(document)

    assert result.ok is True
    _, payload, headers = client.calls[0]
    assert payload == {
        "pathType": "gongci_u1",
        "fileName": "fixture.pdf",
        "orgFileName": "fixture.pdf",
        "filePath": "/uploadwas/life/html/gongci/upload/1/",
    }
    assert headers == AJAX_HEADERS


def test_document_cell_with_crlf_filenames_materializes_each_attachment():
    adapter = _adapter(_Client())
    cells = {
        "cell0": "연금",
        "cell1": "변액연금보험",
        "cell2": "20250401",
        "cell3": "",
        "cell4": "요약서.pdf",
        "cell5": "첫 약관.pdf\r\n둘 약관.pdf",
        "cell6": "사업방법서.pdf",
        "cell7": "/html/gongci/upload/1/",
    }

    version = adapter._to_version(
        {"seq": "p1"}, "판매중", "판매중인상품", cells=cells
    )

    assert [doc.original_filename for doc in version.documents] == [
        "요약서.pdf",
        "첫 약관.pdf",
        "둘 약관.pdf",
        "사업방법서.pdf",
    ]
    assert [doc.download_hint["fileName"] for doc in version.documents] == [
        "요약서.pdf",
        "첫 약관.pdf",
        "둘 약관.pdf",
        "사업방법서.pdf",
    ]
    assert [doc.download_hint["attachmentOrdinal"] for doc in version.documents] == [1, 1, 2, 1]
    assert version.documents[1].source_locator != version.documents[2].source_locator
