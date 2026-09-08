from datetime import date

import pytest

from crawler.base_adapter import FetchResult
from crawler.download_service import DownloadService
from crawler.manifest_service import ManifestRecord, ManifestService
from crawler.path_service import PathService
from models.document import Document, DocumentType, DownloadStatus
from models.product_version import ProductVersion


class _Errors:
    def record(self, **kwargs):
        return None


class _Repository:
    def __init__(self, found=None):
        self.found = found
        self.events = []
        self.probed_keys = []

    def get_by_document_key(self, key):
        self.probed_keys.append(key)
        return self.found

    def load_company_rows(self, _company_code):
        return {}

    def upsert_seen(self, payload):
        self.events.append(("seen", payload))

    def upsert_result(self, payload):
        self.events.append(("result", payload))


class _FailedFetch:
    def fetch_document(self, document):
        return FetchResult(ok=False, status=DownloadStatus.DOWNLOAD_FAILED, reason="test", http_status=500)


def _version():
    return ProductVersion(
        company_code="DB",
        company_name="DB손해보험",
        product_name_raw="테스트상품",
        source_page_url="https://example.test/product",
        source_product_id="P1",
        sale_start_date=date(2024, 1, 1),
    )


def _document():
    return Document(
        DocumentType.POLICY,
        "약관",
        original_filename="policy.pdf",
        download_hint={"filePath": "/upload/", "fileName": "policy.pdf", "attachmentOrdinal": 1},
    )


def test_runtime_writes_current_v4_identity_without_legacy_override(tmp_path):
    paths = PathService(str(tmp_path), "output", target_month="2024-01")
    repository = _Repository()
    manifest = ManifestService(paths.output_root, "RUN", repository=repository)
    manifest.load_previous(company_code="DB")
    service = DownloadService(None, paths, manifest, _Errors())

    service.process_document(_FailedFetch(), _version(), _document())

    assert [event[0] for event in repository.events] == ["seen", "result"]
    assert all(event[1]["identity_version"] == 4 for event in repository.events)
    assert all(event[1]["document_key"].startswith("DOC_") for event in repository.events)
    assert all(event[1]["product_version_key"].startswith("PROD_VER_") for event in repository.events)


def test_runtime_does_not_probe_legacy_sha_keys(tmp_path):
    paths = PathService(str(tmp_path), "output", target_month="2024-01")
    repository = _Repository()
    manifest = ManifestService(paths.output_root, "RUN", repository=repository)
    record = ManifestRecord(
        company_code="DB",
        source_product_id="P1",
        product_name_raw="상품",
        target_date="2024-01-01",
        document_type=DocumentType.POLICY,
        document_url="https://example.test/policy.pdf",
        original_filename="policy.pdf",
    )

    assert manifest.previous_row(record) is None
    assert len(repository.probed_keys) == 1
    assert repository.probed_keys[0].startswith("DOC_")


def test_runtime_rejects_legacy_identity_version_row(tmp_path):
    paths = PathService(str(tmp_path), "output", target_month="2024-01")
    repository = _Repository(
        found={
            "identity_version": 1,
            "document_key": "a" * 64,
            "product_version_key": "b" * 64,
        }
    )
    manifest = ManifestService(paths.output_root, "RUN", repository=repository)
    record = ManifestRecord(
        company_code="DB",
        source_product_id="P1",
        product_name_raw="상품",
        target_date="2024-01-01",
        document_type=DocumentType.POLICY,
        document_url="https://example.test/policy.pdf",
        original_filename="policy.pdf",
    )

    with pytest.raises(RuntimeError, match="legacy identity_version"):
        manifest.previous_row(record)
