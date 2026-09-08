"""CrawlerManager 판매중 재검증·폴더 전환 통합 테스트(네트워크 없음)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from crawler.config import load_config
from crawler.crawler_manager import CrawlerManager, RunOptions
from crawler.manifest_service import ManifestRecord, ManifestService
from crawler.document_repository import StatusUpdateResult, payload_from_record
from crawler.path_service import PathService
from crawler.run_context import RunContext
from models.document import Document, DocumentType, DownloadStatus
from models.product_version import ProductVersion
from utils.file_utils import normalize_storage_component
from utils.crawler_logger import setup_logging
from tests.company_fixtures import company_definition


ROOT = Path(__file__).resolve().parents[1]


class FakeRepository:
    def __init__(self):
        self.rows = {}

    def load_company_rows(self, company_code):
        return {k: v for k, v in self.rows.items() if v.get("company_code") == company_code}

    def upsert_seen(self, payload):
        self.rows[payload["document_key"]] = {**self.rows.get(payload["document_key"], {}), **payload}

    def upsert_result(self, payload):
        self.rows[payload["document_key"]] = {**self.rows.get(payload["document_key"], {}), **payload}

    def update_status_rows_detailed(self, rows):
        rows = list(rows)
        for row in rows:
            self.rows[row["document_key"]] = {**self.rows.get(row["document_key"], {}), **row}
        return StatusUpdateResult(len(rows), len(rows), 0, 0)

    def close(self):
        return None


def _context(run_id: str) -> RunContext:
    if not str(run_id)[:8].isdigit():
        run_id = f"20260820_120000_{run_id}"
    return RunContext(run_id, "TEST-PC", 123, "2026-08-20T12:00:00", "abc")


def _config(tmp_path: Path):
    original = load_config(ROOT / "config.yaml")
    return replace(
        original,
        base_path=str(tmp_path),
        root_folder="상품공시실문서",
    )


class ActiveEndedAdapter:
    code = "DB"
    collection_method = "TEST_ACTIVE_REFRESH"

    def __init__(self, company, config, classifier, *, runtime_options=None):
        del config, classifier
        self.company = company
        self.stats = {}
        self.active_rows = []
        self.document_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def configure_active_status_refresh(self, rows):
        self.active_rows = list(rows)

    def collect_product_versions(self, start_date, end_date):
        del start_date, end_date
        self.stats["status_coverage_complete"] = True
        ended = ProductVersion(
            company_code="DB",
            company_name="DB보험",
            product_name_raw="과거상품",
            source_page_url="https://example.test/old",
            source_product_id="old-1",
            sale_status="판매중지",
            sale_start_date=date(2024, 1, 1),
            sale_end_date=date(2026, 7, 31),
        )
        return [ended]

    def collect_documents(self, version):
        self.document_calls += 1
        return version.documents


class PartialCoverageAdapter(ActiveEndedAdapter):
    def collect_product_versions(self, start_date, end_date):
        versions = super().collect_product_versions(start_date, end_date)
        self.stats["status_coverage_complete"] = False
        return versions


class ActiveOnlyAdapter(ActiveEndedAdapter):
    def collect_product_versions(self, start_date, end_date):
        versions = super().collect_product_versions(start_date, end_date)
        current = ProductVersion(
            company_code="DB",
            company_name="DB보험",
            product_name_raw="신규상품",
            source_page_url="https://example.test/new",
            source_product_id="new-1",
            sale_status="판매중",
            sale_start_date=date(2026, 7, 1),
            documents=[Document(DocumentType.POLICY, "약관", "https://example.test/new.pdf", "new.pdf")],
        )
        return versions + [current]


def _seed_active_manifest(manager: CrawlerManager) -> tuple[Path, str]:
    folder = (
        manager.paths.documents_root
        / "DB보험"
        / "2024"
        / "01"
        / "판매중__20240101_과거상품"
    )
    folder.mkdir(parents=True)
    saved = folder / "약관.pdf"
    saved.write_bytes(b"pdf")
    relative = saved.relative_to(manager.paths.output_root).as_posix()
    record = ManifestRecord(
            company_code="DB",
            company_name="DB보험",
            product_name_raw="과거상품",
            product_name_normalized=normalize_storage_component("과거상품"),
            source_product_id="old-1",
            sale_status="판매중",
            normalized_sale_status="ACTIVE",
            source_sale_status="판매중",
            sale_start_date="2024-01-01",
            target_date="2024-01-01",
            document_type=DocumentType.POLICY,
            document_label="약관",
            document_url="https://example.test/old.pdf",
            original_filename="old.pdf",
            saved_filename="약관.pdf",
            saved_relative_path=relative,
            download_status=DownloadStatus.SUCCESS,
            downloaded_at="2026-08-19T10:00:00",
        )
    version = ProductVersion(
        company_code="DB", company_name="DB보험", product_name_raw="과거상품",
        source_page_url="https://example.test/old", source_product_id="old-1",
        sale_start_date=date(2024, 1, 1), sale_end_date=date(2026, 7, 31),
        sale_status="판매중",
    )
    document = Document(DocumentType.POLICY, "약관", "https://example.test/old.pdf", "old.pdf")
    manager._fake_repo.upsert_result(payload_from_record(record, version=version, document=document, run_id="SEED"))
    return folder, relative


def _manager(tmp_path: Path, adapter, monkeypatch, **options) -> CrawlerManager:
    registry = __import__("crawler.crawler_manager", fromlist=["ADAPTER_REGISTRY"]).ADAPTER_REGISTRY
    monkeypatch.setitem(registry, "DB", adapter)
    repository = FakeRepository()
    config = _config(tmp_path)
    options_value = RunOptions(target_month="2026-07", companies=["DB"], **options)
    manager = CrawlerManager(
        config,
        options_value,
        paths=PathService(
            base_path=config.base_path,
            root_folder=config.root_folder,
            target_month="2026-07",
            scope_key="2026-07",
            storage_kind=config.storage_kind,
        ),
        context=_context("20260820_120000_STATUS"),
        repository_factory=lambda: repository,
    )
    manager._fake_repo = repository
    return manager


def test_manager_moves_active_folder_and_commits_db_without_redownload(tmp_path, monkeypatch):
    setup_logging(None)
    manager = _manager(tmp_path, ActiveEndedAdapter, monkeypatch)
    old_folder, _ = _seed_active_manifest(manager)

    summary = manager.run()

    new_folder = old_folder.with_name("판매완료__20240101_과거상품")
    assert not old_folder.exists()
    assert (new_folder / "약관.pdf").exists()
    rows = list(manager._fake_repo.rows.values())
    assert rows[0]["sale_status"] == "ENDED"
    assert "판매완료__20240101_과거상품" in rows[0]["saved_relative_path"]
    assert not (manager.paths.output_root / "manifest.json").exists()
    assert summary["companies"]["DB"]["document_records"] == 0
    assert summary["companies"]["DB"]["active_status_folder_moved"] == 1
    journal = manager.paths.status_move_journal_path("DB").read_text(encoding="utf-8")
    assert '"phase": "COMMITTED"' in journal


def test_partial_coverage_keeps_existing_active_status_and_folder(tmp_path, monkeypatch):
    setup_logging(None)
    manager = _manager(tmp_path, PartialCoverageAdapter, monkeypatch)
    old_folder, _ = _seed_active_manifest(manager)

    summary = manager.run()

    assert old_folder.exists()
    rows = list(manager._fake_repo.rows.values())
    assert rows[0]["sale_status"] == "ACTIVE"
    assert summary["companies"]["DB"]["active_status_coverage_complete"] is False


def test_refresh_active_only_does_not_download_current_period_documents(tmp_path, monkeypatch):
    setup_logging(None)
    manager = _manager(
        tmp_path,
        ActiveOnlyAdapter,
        monkeypatch,
        refresh_active_only=True,
    )
    _seed_active_manifest(manager)

    summary = manager.run()

    company = summary["companies"]["DB"]
    assert company["selected_versions"] == 0
    assert company["document_records"] == 0
    assert company["status"] == "SUCCESS"
