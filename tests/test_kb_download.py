"""KB 파일 다운로드의 EUC-KR ``fileNm`` 보정 계약 테스트."""

from types import SimpleNamespace

from crawler.adapters.kb_insurance import KBInsuranceAdapter
from models.document import Document


class _Response:
    status_code = 200

    def __init__(self, url, content, content_type):
        self.url = url
        self.content = content
        self.headers = {"content-type": content_type}


class _Client:
    def __init__(self, first_content=b"<!doctype html>\n\xb1\xa4\xb0\xed", first_type="text/html; charset=EUC-KR",
                 second_content=b"%PDF-1.7\nfixture", second_type="application/pdf"):
        self.calls = []
        self.first_content = first_content
        self.first_type = first_type
        self.second_content = second_content
        self.second_type = second_type

    def get(self, url):
        self.calls.append(url)
        # 실제 KB 오류 응답처럼 상태 200 + EUC-KR HTML인 경우를 모의한다.
        if len(self.calls) == 1:
            return _Response(url, self.first_content, self.first_type)
        return _Response(url, self.second_content, self.second_type)


def _adapter(client):
    adapter = KBInsuranceAdapter.__new__(KBInsuranceAdapter)
    adapter.company = SimpleNamespace(options={})
    adapter.code = "KB"
    adapter.name = "KB손해보험"
    adapter.base_url = "https://example.test"
    adapter.log = __import__("logging").getLogger("kb-download-contract")
    adapter._active_status_rows = []
    adapter._client = client
    return adapter


def test_kb_retries_html_response_with_euckr_file_name_encoding():
    client = _Client()
    adapter = _adapter(client)
    document = Document(
        document_type="METHOD",
        document_label="사업방법서",
        document_url="https://example.test/CG802030003.ec?fileNm=사업방법서.pdf",
        original_filename="사업방법서.pdf",
    )

    result = adapter.fetch_document(document)

    assert result.ok is True
    assert result.content.startswith(b"%PDF-")
    assert len(client.calls) == 2
    assert client.calls[0] == document.document_url
    assert "%BB%E7%BE%F7%B9%E6%B9%FD%BC%AD.pdf" in client.calls[1]


def test_kb_does_not_change_ascii_file_url_when_no_encoding_is_needed():
    url = "https://example.test/CG802030003.ec?fileNm=20260101_10101_2.pdf"
    assert KBInsuranceAdapter._euckr_file_url_variants(url) == []


def test_kb_retries_html_comment_response_for_non_ascii_pdf_name():
    """KB 오류 응답 중 ``<!-- Fast...`` 선두 형태도 보정한다."""
    client = _Client(first_content=b"<!-- Fast error page -->", first_type="text/plain")
    adapter = _adapter(client)
    document = Document(
        document_type="METHOD",
        document_label="사업방법서",
        document_url="https://example.test/CG802030003.ec?fileNm=사업방법서.pdf",
        original_filename="사업방법서.pdf",
    )

    result = adapter.fetch_document(document)

    assert result.ok is True
    assert len(client.calls) == 2


def test_kb_does_not_retry_non_html_drm_payload():
    """PDF 이름이어도 HTML이 아닌 DRM/바이너리 응답은 재요청하지 않는다."""
    client = _Client(first_content=b"DRM-PAYLOAD", first_type="application/octet-stream")
    adapter = _adapter(client)
    document = Document(
        document_type="METHOD",
        document_label="사업방법서",
        document_url="https://example.test/CG802030003.ec?fileNm=사업방법서.pdf",
        original_filename="사업방법서.pdf",
    )

    result = adapter.fetch_document(document)

    assert result.ok is True
    assert result.content == b"DRM-PAYLOAD"
    assert len(client.calls) == 1


def test_kb_does_not_log_html_comment_retry_as_success():
    """EUC-KR 재시도의 두 번째 응답도 HTML이면 성공 분기로 가지 않는다."""
    client = _Client(
        first_content=b"<!-- Fast error page -->",
        first_type="text/plain",
        second_content=b"<!-- Fast error page (euc-kr) -->",
        second_type="text/plain",
    )
    adapter = _adapter(client)
    info_messages = []
    adapter.log = SimpleNamespace(info=lambda *args, **kwargs: info_messages.append(args))
    document = Document(
        document_type="METHOD",
        document_label="사업방법서",
        document_url="https://example.test/CG802030003.ec?fileNm=사업방법서.pdf",
        original_filename="사업방법서.pdf",
    )

    result = adapter.fetch_document(document)

    assert result.content.startswith(b"<!--")
    assert len(client.calls) == 2
    assert info_messages == []
