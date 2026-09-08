"""다운로드 staging 파일의 원자 publish 및 정리 테스트."""

from datetime import date
from pathlib import Path

import crawler.download_service as download_module
from crawler.base_adapter import FetchResult
from crawler.config import load_config
from crawler.download_service import DownloadService
from crawler.manifest_service import ManifestService
from crawler.path_service import PathService
from crawler.validators import ValidationResult, validate_saved_file as real_validate_saved_file
from models.document import Document, DocumentType, DownloadStatus
from models.product_version import ProductVersion
from utils.crawler_logger import ErrorRecorder, setup_logging


ROOT = Path(__file__).resolve().parents[1]
PDF = (ROOT / "tests" / "fixtures" / "sample.pdf").read_bytes()


class FakeAdapter:
    def __init__(self, payload: bytes = PDF):
        self.payload = payload

    def collect_documents(self, version):
        return version.documents

    def fetch_document(self, document):
        return FetchResult(
            ok=True,
            status=DownloadStatus.SUCCESS,
            content=self.payload,
            content_type="application/pdf",
            original_filename="원본_약관.pdf",
            http_status=200,
        )


def make_service(tmp_path: Path):
    setup_logging(None)
    config = load_config(ROOT / "config.yaml")
    paths = PathService(
        base_path=str(tmp_path),
        root_folder="insurance_product_documents",
        target_month="2026-07",
        max_path_length=config.max_path_length,
    )
    run_id = "20260820_143000_ab12cd"
    staging = paths.download_staging_dir("RUN-STAGING", "DB")
    manifest = ManifestService(
        output_root=paths.output_root,
        run_id="RUN-STAGING",
        audit_event_path=paths.run_journal_path(run_id, "DB"),
    )
    service = DownloadService(
        config=config,
        paths=paths,
        manifest=manifest,
        errors=ErrorRecorder(None),
    )
    return service, paths, staging


def make_version() -> ProductVersion:
    version = ProductVersion(
        company_code="DB",
        company_name="DB손해보험", storage_name="DB손해보험",
        product_name_raw="테스트보험",
        source_page_url="https://example.test",
        source_product_id="1234",
        sale_status="판매중",
        sale_start_date=date(2026, 7, 15),
        version_key="20260715_판매개시",
    )
    version.documents.append(
        Document(
            document_type=DocumentType.POLICY,
            document_label="보험약관",
            document_url="https://example.test/a.pdf",
            original_filename="a.pdf",
        )
    )
    return version


def test_success_publishes_from_staging_and_cleans_it(tmp_path):
    service, paths, staging = make_service(tmp_path)

    record = service.process_version(FakeAdapter(), make_version())[0]

    assert record.download_status == DownloadStatus.SUCCESS
    saved = paths.resolve_relative_path(record.saved_relative_path)
    assert saved.exists()
    assert saved.read_bytes() == PDF
    assert not list(staging.rglob("*"))
    assert not list(paths.company_dir("DB손해보험").rglob(".part_*"))


def test_publish_failure_cleans_staging_and_leaves_documents_empty(tmp_path, monkeypatch):
    service, paths, staging = make_service(tmp_path)

    def fail_replace(source, target):
        assert Path(source).parent == staging
        raise OSError("publish failed")

    monkeypatch.setattr(download_module.os, "rename", fail_replace)
    record = service.process_version(FakeAdapter(), make_version())[0]

    assert record.download_status == DownloadStatus.DOWNLOAD_FAILED
    assert not list(staging.rglob("*"))
    assert not list(paths.company_dir("DB손해보험").rglob("*.pdf"))


def test_final_validation_failure_removes_only_newly_published_file(tmp_path, monkeypatch):
    service, paths, staging = make_service(tmp_path)
    version = make_version()
    original, _ = paths.resolve_target_path(version, DocumentType.POLICY, ".pdf", "원본_약관.pdf")
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(b"%PDF-1.4 pre-existing content")
    published = paths.next_available_path(original)
    calls = 0

    def fail_final_validation(path, expected_size, extension):
        nonlocal calls
        calls += 1
        if calls == 2:  # staging 검증은 통과시키고, publish 직후 최종 검증만 실패
            return ValidationResult(False, DownloadStatus.INVALID_FILE, "최종 검증 실패")
        return real_validate_saved_file(path, expected_size, extension)

    monkeypatch.setattr(download_module, "validate_saved_file", fail_final_validation)
    record = service.process_version(FakeAdapter(), version)[0]

    assert record.download_status == DownloadStatus.DOWNLOAD_FAILED
    assert original.read_bytes() == b"%PDF-1.4 pre-existing content"
    assert not published.exists()
    assert not list(staging.rglob("*"))
