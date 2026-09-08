"""CrawlerManager의 잠금·메타데이터 분리 통합 테스트(네트워크 없음)."""

import json
import multiprocessing
import pytest
from dataclasses import replace
from datetime import date
from pathlib import Path

from crawler.config import load_config
from crawler.base_adapter import FetchResult
from crawler.crawler_manager import CrawlerManager, RunOptions
from crawler.document_repository import StatusUpdateResult
from crawler.lock_service import CompanyLock
from crawler.path_service import PathService
from crawler.plan_service import PlanService
from crawler.run_context import RunContext
from models.document import Document, DocumentType, DownloadStatus
from models.product_version import ProductVersion
from utils.crawler_logger import setup_logging
from tests.company_fixtures import company_definition

ROOT = Path(__file__).resolve().parents[1]


class FakeRepository:
    """DB 없이 문서 상태 UPSERT/체크포인트를 검증하는 in-memory 저장소."""

    def __init__(self):
        self.rows = {}

    @classmethod
    def from_env(cls, *args, **kwargs):
        return cls()

    def load_company_rows(self, company_code):
        return {key: row for key, row in self.rows.items() if row.get("company_code") == company_code}

    def get_by_document_key(self, key):
        return self.rows.get(key)

    def upsert_seen(self, payload):
        self.rows[payload["document_key"]] = {**self.rows.get(payload["document_key"], {}), **payload}

    def upsert_result(self, payload):
        self.rows[payload["document_key"]] = {**self.rows.get(payload["document_key"], {}), **payload}

    def update_status_rows_detailed(self, rows):
        rows = list(rows)
        for row in rows:
            key = row["document_key"]
            self.rows[key] = {**self.rows.get(key, {}), **row}
        return StatusUpdateResult(len(rows), len(rows), 0, 0)

    def close(self):
        return None


@pytest.fixture(autouse=True)
def _fake_database(monkeypatch):
    monkeypatch.setattr(CrawlerManager, "_open_repository", lambda self: FakeRepository())


class FakeAdapter:
    code = "DB"
    collection_method = "TEST"

    def __init__(self, company, config, classifier, *, runtime_options=None):
        self.company = company
        self.stats = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def collect_product_versions(self, start_date, end_date):
        version = ProductVersion(
            company_code=self.company.code,
            company_name=self.company.name,
            storage_name=self.company.storage_name,
            product_name_raw="테스트상품",
            product_category="테스트종류",
            source_product_id="1",
            source_page_url="https://example.test",
            sale_status="판매중",
            sale_start_date=date(2026, 7, 1),
        )
        version.documents.append(Document(
            document_type=DocumentType.POLICY,
            document_label="보험약관",
            document_url="https://example.test/policy.pdf",
            original_filename="원본약관.pdf",
        ))
        return [version]

    def collect_documents(self, version):
        return version.documents


class FakeHintAdapter(FakeAdapter):
    """URL 대신 POST 다운로드 힌트를 제공하는 Adapter 스텁."""

    def collect_product_versions(self, start_date, end_date):
        versions = super().collect_product_versions(start_date, end_date)
        versions[0].documents = [Document(
            document_type=DocumentType.POLICY,
            document_label="보험약관",
            original_filename="POST_약관.pdf",
            download_hint={"fileName": "POST_약관.pdf", "filePath": "/documents"},
        )]
        return versions


class FailingDownloadAdapter(FakeAdapter):
    def fetch_document(self, document):
        return FetchResult(
            ok=False,
            status=DownloadStatus.DOWNLOAD_FAILED,
            reason="테스트 다운로드 실패",
            http_status=500,
        )


class PrefilteringAdapter(FakeAdapter):
    """원본 행은 많지만 기간 후보만 객체로 만드는 어댑터 스텁."""

    def collect_product_versions(self, start_date, end_date):
        self.stats.update(raw_rows=10, materialized_rows=1, filtered_rows=9)
        return super().collect_product_versions(start_date, end_date)


def run_context(run_id: str, _operator: str = "테스트사용자") -> RunContext:
    if not str(run_id)[:8].isdigit():
        run_id = f"20260818_100000_{run_id}"
    return RunContext(run_id, "TEST-PC", 123, "2026-08-18T10:00:00", "abc123")


def app_config(tmp_path, codes=("DB",)):
    original = load_config(ROOT / "config.yaml")
    return replace(
        original,
        base_path=str(tmp_path),
        root_folder="상품공시실문서",
    )


def make_manager(config, options, **kwargs) -> CrawlerManager:
    scope_key = options.scope_key or options.target_month or "test-scope"
    paths = PathService(
        base_path=config.base_path,
        root_folder=config.root_folder,
        target_month=options.target_month or scope_key,
        max_path_length=config.max_path_length,
        scope_key=scope_key,
        storage_kind=config.storage_kind,
        local_staging_override=config.local_staging_path,
        local_state_override=config.local_state_path,
    )
    return CrawlerManager(config, options, paths=paths, **kwargs)


def _manager_worker(base_path: str, code: str, run_id: str, results) -> None:
    setup_logging(None)
    registry = __import__("crawler.crawler_manager", fromlist=["ADAPTER_REGISTRY"]).ADAPTER_REGISTRY
    registry[code] = type(f"{code}FakeAdapter", (FakeAdapter,), {"code": code})
    manager = make_manager(
        app_config(Path(base_path), (code,)),
        RunOptions(target_month="2026-07", companies=[code], dry_run=True),
        context=run_context(run_id, f"{code}사용자"),
        repository_factory=FakeRepository,
    )
    summary = manager.run()
    results.put((code, summary["run_status"], str(manager.summary_path)))


def test_manager_writes_db_state_and_run_summary_without_manifest(tmp_path, monkeypatch):
    setup_logging(None)
    monkeypatch.setitem(__import__("crawler.crawler_manager", fromlist=["ADAPTER_REGISTRY"]).ADAPTER_REGISTRY,
                        "DB", FakeAdapter)
    manager = make_manager(
        app_config(tmp_path),
        RunOptions(target_month="2026-07", companies=["DB"], dry_run=True),
        context=run_context("RUN_A"),
    )
    summary = manager.run()

    assert manager.summary_path.exists()
    assert not (manager.paths.output_root / "manifest.json").exists()
    assert not (manager.paths.output_root / "manifest.csv").exists()
    assert not (manager.paths.output_root / "02_수집목록").exists()
    assert "operator" not in summary
    assert summary["run_status"] == "SUCCESS"
    assert not manager.paths.lock_path("DB").exists()


def test_manager_counts_download_hint_as_document_link(tmp_path, monkeypatch):
    setup_logging(None)
    registry = __import__("crawler.crawler_manager", fromlist=["ADAPTER_REGISTRY"]).ADAPTER_REGISTRY
    monkeypatch.setitem(registry, "DB", FakeHintAdapter)
    manager = make_manager(
        app_config(tmp_path),
        RunOptions(target_month="2026-07", companies=["DB"], dry_run=True),
        context=run_context("RUN_HINT"),
    )

    summary = manager.run()

    assert summary["companies"]["DB"]["document_links"] == 1
    assert not (manager.paths.output_root / "manifest.json").exists()


def test_manager_preserves_raw_collected_count_for_prefiltering_adapter(tmp_path, monkeypatch):
    setup_logging(None)
    registry = __import__("crawler.crawler_manager", fromlist=["ADAPTER_REGISTRY"]).ADAPTER_REGISTRY
    monkeypatch.setitem(registry, "DB", PrefilteringAdapter)
    manager = make_manager(
        app_config(tmp_path),
        RunOptions(target_month="2026-07", companies=["DB"], dry_run=True),
        context=run_context("RUN_PREFILTER"),
    )

    summary = manager.run()

    company = summary["companies"]["DB"]
    assert company["collected_versions"] == 10
    assert company["materialized_rows"] == 1
    assert company["selected_versions"] == 1


def test_manager_marks_company_failed_when_documents_need_retry(tmp_path, monkeypatch):
    setup_logging(None)
    registry = __import__("crawler.crawler_manager", fromlist=["ADAPTER_REGISTRY"]).ADAPTER_REGISTRY
    monkeypatch.setitem(registry, "DB", FailingDownloadAdapter)
    manager = make_manager(
        app_config(tmp_path),
        RunOptions(target_month="2026-07", companies=["DB"]),
        context=run_context("RUN_FAILED_DOCUMENT"),
    )

    summary = manager.run()

    assert summary["run_status"] == "FAILED"
    assert summary["failed_companies"] == ["DB"]
    assert summary["companies"]["DB"]["status_counts"] == {
        DownloadStatus.DOWNLOAD_FAILED: 1
    }
    assert "재시도 필요한 문서 1건" in summary["companies"]["DB"]["error"]


def test_manager_reports_existing_company_lock_without_touching_manifest(tmp_path, monkeypatch):
    setup_logging(None)
    monkeypatch.setitem(__import__("crawler.crawler_manager", fromlist=["ADAPTER_REGISTRY"]).ADAPTER_REGISTRY,
                        "DB", FakeAdapter)
    config = app_config(tmp_path)
    manager = make_manager(
        config,
        RunOptions(target_month="2026-07", companies=["DB"], dry_run=True),
        context=run_context("RUN_CURRENT"),
    )
    existing = CompanyLock(
        manager.paths.lock_path("DB"), "DB", "DB보험", "2026-06", run_context("RUN_OTHER")
    )
    existing.acquire()
    try:
        summary = manager.run()
    finally:
        existing.release()

    assert summary["run_status"] == "LOCKED"
    assert summary["locked_companies"] == ["DB"]
    assert summary["companies"]["DB"]["lock_owner"]["run_id"] == "20260818_100000_RUN_OTHER"
    assert not (manager.paths.output_root / "manifest.json").exists()


def test_different_companies_keep_db_state_without_global_manifest(tmp_path, monkeypatch):
    setup_logging(None)
    registry = __import__("crawler.crawler_manager", fromlist=["ADAPTER_REGISTRY"]).ADAPTER_REGISTRY
    monkeypatch.setitem(registry, "DB", FakeAdapter)
    monkeypatch.setitem(registry, "LOTTE", type("LotteFakeAdapter", (FakeAdapter,), {"code": "LOTTE"}))
    manager = make_manager(
        app_config(tmp_path, ("DB", "LOTTE")),
        RunOptions(target_month="2026-07", companies=["DB", "LOTTE"], dry_run=True),
        context=run_context("RUN_B"),
    )
    summary = manager.run()

    assert summary["run_status"] == "SUCCESS"
    assert not (manager.paths.output_root / "manifest.json").exists()
    assert not (manager.paths.output_root / "manifest.csv").exists()


def test_different_companies_run_concurrently_in_separate_processes(tmp_path):
    process_context = multiprocessing.get_context("spawn")
    results = process_context.Queue()
    processes = [
        process_context.Process(
            target=_manager_worker,
            args=(str(tmp_path), code, f"RUN_{code}", results),
        )
        for code in ("DB", "LOTTE")
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(15)
        if process.is_alive():
            process.terminate()
            process.join(5)

    assert [process.exitcode for process in processes] == [0, 0]
    outcomes = {results.get(timeout=2)[0] for _ in processes}
    assert outcomes == {"DB", "LOTTE"}
    manifest_root = tmp_path / "상품공시실문서" / "02_수집목록"
    assert not manifest_root.exists()


def test_manager_reports_orphan_part_files_without_deleting_them(tmp_path, monkeypatch):
    setup_logging(None)
    registry = __import__("crawler.crawler_manager", fromlist=["ADAPTER_REGISTRY"]).ADAPTER_REGISTRY
    monkeypatch.setitem(registry, "DB", FakeAdapter)
    manager = make_manager(
        app_config(tmp_path),
        RunOptions(target_month="2026-07", companies=["DB"], dry_run=True),
        context=run_context("RUN_PART"),
    )
    staging_dir = manager.paths.download_staging_dir("OLD_RUN", "DB")
    staging_dir.mkdir(parents=True)
    orphan = staging_dir / ".part_OLD_deadbeef.pdf"
    orphan.write_bytes(b"partial")

    summary = manager.run()

    assert summary["companies"]["DB"]["orphan_part_file_count"] == 1
    assert "orphan_part_files" not in summary["companies"]["DB"]
    assert orphan.exists()


def test_period_run_writes_download_plan_and_monthly_index(tmp_path, monkeypatch):
    setup_logging(None)
    registry = __import__("crawler.crawler_manager", fromlist=["ADAPTER_REGISTRY"]).ADAPTER_REGISTRY
    monkeypatch.setitem(registry, "DB", FakeAdapter)
    manager = make_manager(
        app_config(tmp_path),
        RunOptions(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            scope_key="20260101_20261231",
            companies=["DB"],
            dry_run=True,
            write_plan=True,
        ),
        context=run_context("RUN_PLAN"),
    )

    summary = manager.run()

    plan_relative_path = summary["companies"]["DB"]["download_plan"]
    assert not Path(plan_relative_path).is_absolute()
    plan_path = manager.paths.resolve_relative_path(plan_relative_path)
    assert plan_path.exists()
    assert len(PlanService(plan_path).items()) == 1
    assert (plan_path.parent / "months.v3" / "2026-07.json").exists()
    assert summary["scope_key"] == "20260101_20261231"


def test_download_plan_does_not_collect_product_versions(tmp_path, monkeypatch):
    setup_logging(None)

    class PlanOnlyAdapter(FakeAdapter):
        collect_calls = 0

        def collect_product_versions(self, start_date, end_date):
            type(self).collect_calls += 1
            raise AssertionError("plan 다운로드에서 상품 목록을 재수집하면 안 됩니다")

    registry = __import__("crawler.crawler_manager", fromlist=["ADAPTER_REGISTRY"]).ADAPTER_REGISTRY
    monkeypatch.setitem(registry, "DB", PlanOnlyAdapter)
    pending_count_calls = []
    original_pending_count = PlanService.pending_count

    def pending_count_without_unc_stat(self, *, verify_files=True):
        pending_count_calls.append(verify_files)
        return original_pending_count(self, verify_files=verify_files)

    monkeypatch.setattr(PlanService, "pending_count", pending_count_without_unc_stat)
    plan_path = tmp_path / "상품공시실문서" / "99_운영" / "plans" / "input_plan.jsonl"
    plan = PlanService(plan_path)
    version = ProductVersion(
        company_code="DB",
        company_name="DB보험",
        storage_name="DB손해보험",
        product_name_raw="계획상품",
        source_page_url="https://example.test",
        source_product_id="plan-1",
        sale_start_date=date(2026, 7, 1),
        documents=[Document(
            document_type=DocumentType.POLICY,
            document_label="보험약관",
            document_url="https://example.test/plan.pdf",
            original_filename="plan.pdf",
        )],
    )
    plan.add_version(version, version.documents[0])
    manager = make_manager(
        app_config(tmp_path),
        RunOptions(
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 1),
            scope_key="20260701_20260701",
            companies=["DB"],
            dry_run=True,
            download_plan=str(plan_path),
        ),
        context=run_context("RUN_PLAN_DOWNLOAD"),
    )

    summary = manager.run()

    assert summary["run_status"] == "SUCCESS"
    assert PlanOnlyAdapter.collect_calls == 0
    assert summary["companies"]["DB"]["document_records"] == 1
    assert False in pending_count_calls


def test_download_plan_reports_existing_lock_without_traceback(tmp_path, monkeypatch):
    setup_logging(None)
    registry = __import__("crawler.crawler_manager", fromlist=["ADAPTER_REGISTRY"]).ADAPTER_REGISTRY
    monkeypatch.setitem(registry, "DB", FakeAdapter)
    plan_path = tmp_path / "상품공시실문서" / "99_운영" / "plans" / "locked_plan.jsonl"
    plan = PlanService(plan_path)
    version = FakeAdapter(company_definition("DB", "DB보험"), None, None).collect_product_versions(None, None)[0]
    plan.add_version(version, version.documents[0])
    original = plan_path.read_bytes().rstrip(b"\r\n")
    plan_path.write_bytes(original)
    manager = make_manager(
        app_config(tmp_path),
        RunOptions(
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 1),
            scope_key="20260701_20260701",
            companies=["DB"],
            download_plan=str(plan_path),
        ),
        context=run_context("RUN_LOCKED_PLAN"),
    )
    existing = CompanyLock(
        manager.paths.lock_path("DB"), "DB", "DB보험", manager.scope_key,
        run_context("RUN_OTHER_PLAN"),
    )
    existing.acquire()
    try:
        summary = manager.run()
    finally:
        existing.release()

    assert summary["run_status"] == "LOCKED"
    assert summary["locked_companies"] == ["DB"]
    assert summary["failed_companies"] == []
    assert plan_path.read_bytes() == original


def test_download_plan_is_failed_while_retryable_items_remain(tmp_path, monkeypatch):
    setup_logging(None)
    registry = __import__("crawler.crawler_manager", fromlist=["ADAPTER_REGISTRY"]).ADAPTER_REGISTRY
    monkeypatch.setitem(registry, "DB", FailingDownloadAdapter)
    plan_path = tmp_path / "상품공시실문서" / "99_운영" / "plans" / "download_plan.v3.jsonl"
    plan = PlanService(plan_path)
    version = FakeAdapter(
        company_definition("DB", "DB보험"), None, None
    ).collect_product_versions(None, None)[0]
    plan.add_version(version, version.documents[0])
    manager = make_manager(
        app_config(tmp_path),
        RunOptions(
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 1),
            scope_key="20260701_20260701",
            companies=["DB"],
            download_plan=str(plan_path),
        ),
        context=run_context("RUN_FAILED_PLAN"),
    )

    summary = manager.run()

    info = summary["companies"]["DB"]
    assert summary["run_status"] == "FAILED"
    assert info["remaining_documents"] == 1
    assert info["status_counts"][DownloadStatus.DOWNLOAD_FAILED] == 1
