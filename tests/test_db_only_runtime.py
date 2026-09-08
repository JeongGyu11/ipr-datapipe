"""DB 정본 전환 회귀 테스트."""

from datetime import date

import pytest

from crawler.download_service import DownloadService
from crawler.crawler_manager import CrawlerManager
from crawler.manifest_service import ManifestService
from crawler.path_service import PathService
from models.document import Document, DocumentType
from models.product_version import ProductVersion


class FakeRepository:
    def __init__(self):
        self.seen = []
        self.results = []

    def upsert_seen(self, payload):
        self.seen.append(payload)

    def upsert_result(self, payload):
        self.results.append(payload)


def test_document_result_is_upserted_and_only_audit_event_is_created(tmp_path):
    repository = FakeRepository()
    audit = tmp_path / "runs" / "events" / "DB.jsonl"
    manifest = ManifestService(tmp_path, "RUN", audit_event_path=audit, repository=repository)
    service = object.__new__(DownloadService)
    service.manifest = manifest
    service.dry_run = True
    service.outbox = None

    version = ProductVersion(
        company_code="DB",
        company_name="DB손해보험",
        product_name_raw="테스트 상품",
        source_page_url="https://example.test/product",
        source_product_id="P1",
        sale_start_date=date(2024, 1, 1),
    )
    document = Document(DocumentType.POLICY, "약관", "https://example.test/policy.pdf")
    record = service._base_record(version, document)
    record.download_status = "DRY_RUN"
    service._add(version, document, record)

    assert len(repository.results) == 1
    assert repository.results[0]["document_key"]
    assert audit.exists()
    assert not (tmp_path / "manifest.csv").exists()
    assert not (tmp_path / "manifest.json").exists()


def test_path_service_has_no_manifest_output_paths(tmp_path):
    service = PathService(str(tmp_path), "output", target_month="2024-01")
    assert not hasattr(service, "manifest_json_path")
    assert not hasattr(service, "manifest_csv_path")
    assert not hasattr(service, "manifest_lock_path")


def test_repository_factory_cannot_silently_disable_db_only_runtime():
    manager = object.__new__(CrawlerManager)
    manager.repository_factory = lambda: None

    with pytest.raises(RuntimeError, match="DB repository"):
        manager._open_repository()


def test_repository_factory_requires_explicit_close_contract():
    manager = object.__new__(CrawlerManager)
    manager.repository_factory = object

    with pytest.raises(RuntimeError, match=r"close\(\)"):
        manager._open_repository()
