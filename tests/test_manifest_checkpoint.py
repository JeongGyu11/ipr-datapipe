"""DB 체크포인트·감사 이벤트 회귀 테스트."""

from datetime import date
import hashlib

import pytest

from crawler.base_adapter import FetchResult
from crawler.crawler_manager import CrawlerManager
from crawler.db_outbox import DatabaseOutbox
from crawler.document_identity import document_key_for_manifest
from crawler.document_repository import StatusUpdateResult
from crawler.download_service import DownloadService
from crawler.manifest_service import ManifestRecord, ManifestService
from crawler.path_service import PathService
from models.document import Document, DocumentType, DownloadStatus
from models.product_version import ProductVersion


class FakeRepository:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.events = []
        self.seen = []
        self.results = []

    def load_company_rows(self, company_code):
        return {key: row for key, row in self.rows.items() if row.get("company_code") == company_code}

    def get_by_document_key(self, key):
        return self.rows.get(key)

    def upsert_result(self, payload):
        self.events.append(("result", payload))
        self.results.append(payload)
        self.rows[payload["document_key"]] = payload

    def upsert_seen(self, payload):
        self.events.append(("seen", payload))
        self.seen.append(payload)
        self.rows[payload["document_key"]] = payload

    def update_status_rows_detailed(self, rows):
        rows = list(rows)
        for row in rows:
            self.rows[row["document_key"]] = {**self.rows.get(row["document_key"], {}), **row}
        return StatusUpdateResult(len(rows), len(rows), 0, 0)


def version():
    return ProductVersion(
        company_code="DB",
        company_name="DB손해보험",
        product_name_raw="테스트상품",
        source_page_url="https://example.test/product",
        source_product_id="P1",
        sale_start_date=date(2024, 1, 1),
    )


def test_db_rows_are_loaded_as_checkpoint_and_manifest_files_are_not_created(tmp_path):
    existing = {
        "db-key": {
            "document_key": "db-key",
            "company_code": "DB",
            "company_name": "DB손해보험",
            "product_name": "테스트상품",
            "product_name_normalized": "테스트상품",
            "document_type": "POLICY",
            "document_date": date(2024, 1, 1),
            "file_status": "AVAILABLE",
            "last_attempt_status": "SUCCESS",
            "saved_relative_path": "01_문서/DB손해보험/약관.pdf",
            "sha256": "a" * 64,
        }
    }
    repository = FakeRepository(existing)
    service = ManifestService(tmp_path, "RUN", repository=repository)
    rows = service.load_previous(company_code="DB")

    assert rows
    assert service.previous_rows_for_company("DB")[0]["saved_relative_path"].endswith("약관.pdf")
    assert not (tmp_path / "manifest.csv").exists()
    assert not (tmp_path / "manifest.json").exists()


def test_available_file_with_dry_run_attempt_keeps_completed_checkpoint(tmp_path):
    repository = FakeRepository({
        "db-key": {
            "document_key": "db-key",
            "company_code": "DB",
            "company_name": "DB손해보험",
            "product_name": "테스트상품",
            "product_name_normalized": "테스트상품",
            "document_type": "POLICY",
            "document_date": date(2024, 1, 1),
            "file_status": "AVAILABLE",
            "last_attempt_status": "DRY_RUN",
            "saved_relative_path": "01_문서/DB손해보험/약관.pdf",
            "sha256": "a" * 64,
        }
    })
    service = ManifestService(tmp_path, "RUN", repository=repository)

    service.load_previous(company_code="DB")

    assert service.previous_rows_for_company("DB")[0]["download_status"] == DownloadStatus.SUCCESS


@pytest.mark.parametrize(
    ("file_status", "attempt", "expected"),
    [
        ("AVAILABLE", DownloadStatus.SUCCESS, DownloadStatus.SUCCESS),
        ("INVALID", DownloadStatus.SUCCESS, DownloadStatus.INVALID_FILE),
        ("UNAVAILABLE", DownloadStatus.SUCCESS, DownloadStatus.DOWNLOAD_FAILED),
        ("PENDING", DownloadStatus.DUPLICATE_SKIPPED, DownloadStatus.DOWNLOAD_FAILED),
        ("", DownloadStatus.SUCCESS, DownloadStatus.DOWNLOAD_FAILED),
        ("MANUAL_REVIEW", DownloadStatus.DUPLICATE_SKIPPED, DownloadStatus.DOWNLOAD_FAILED),
    ],
)
def test_db_file_status_controls_completed_checkpoint_projection(
    tmp_path, file_status, attempt, expected
):
    service = ManifestService(tmp_path, "RUN")
    row = {
        "company_code": "DB",
        "product_name": "테스트상품",
        "document_type": "POLICY",
        "document_date": date(2024, 1, 1),
        "file_status": file_status,
        "last_attempt_status": attempt,
        "saved_relative_path": "01_문서/DB손해보험/약관.pdf",
    }

    projected = service._db_row_to_checkpoint(row)

    assert projected["download_status"] == expected


def test_document_result_is_upserted_once_and_audit_event_is_append_only(tmp_path):
    repository = FakeRepository()
    audit = tmp_path / "events" / "DB.jsonl"
    manifest = ManifestService(tmp_path, "RUN", audit_event_path=audit, repository=repository)
    service = object.__new__(DownloadService)
    service.manifest = manifest
    service.dry_run = True
    service.outbox = None
    doc = Document(DocumentType.POLICY, "약관", "https://example.test/policy.pdf")
    current_version = version()
    record = service._base_record(current_version, doc)
    record.download_status = "DRY_RUN"
    service._add(current_version, doc, record)

    assert len(repository.results) == 1
    assert audit.read_text(encoding="utf-8").count("\n") == 1
    assert not (tmp_path / "manifest.csv").exists()
    assert not (tmp_path / "manifest.json").exists()


def test_audit_write_failure_does_not_block_terminal_db_upsert(tmp_path, monkeypatch):
    repository = FakeRepository()
    manifest = ManifestService(tmp_path, "RUN", repository=repository)
    service = object.__new__(DownloadService)
    service.manifest = manifest
    service.outbox = None
    current_version = version()
    document = Document(DocumentType.POLICY, "약관", "https://example.test/policy.pdf")
    record = service._base_record(current_version, document)
    record.download_status = DownloadStatus.DOWNLOAD_FAILED

    def fail_audit(_record):
        raise OSError("감사 파일 쓰기 실패")

    monkeypatch.setattr(manifest, "_append_audit_event", fail_audit)

    result = service._add(current_version, document, record)

    assert result is record
    assert len(repository.results) == 1
    assert repository.results[0]["last_attempt_status"] == DownloadStatus.DOWNLOAD_FAILED


def test_checkpoint_row_remains_available_for_lookup_after_file_removal(tmp_path):
    path = tmp_path / "document.pdf"
    path.write_bytes(b"pdf")
    record = ManifestRecord(
        company_code="DB",
        source_product_id="P1",
        product_name_raw="테스트상품",
        target_date="2024-01-01",
        document_type=DocumentType.POLICY,
        document_url="https://example.test/policy.pdf",
        download_status="SUCCESS",
        saved_relative_path="document.pdf",
    )
    service = ManifestService(tmp_path, "RUN")
    service.previous[record.key()] = record.to_row()
    assert service.previous_row(record)["saved_relative_path"] == "document.pdf"
    path.unlink()
    assert service.previous_row(record)["saved_relative_path"] == "document.pdf"


def test_duplicate_checkpoint_without_saved_relative_path_is_not_a_valid_file():
    service = object.__new__(DownloadService)

    assert service._previous_file_ok({
        "download_status": DownloadStatus.DUPLICATE_SKIPPED,
        "saved_relative_path": "",
    }) is False


class _RedirectFailureAdapter:
    def __init__(self):
        self.calls = 0

    def fetch_document(self, document):
        self.calls += 1
        return FetchResult(
            ok=False,
            status=DownloadStatus.DOWNLOAD_FAILED,
            reason="redirect 후 서버 오류",
            http_status=500,
            final_url="https://cdn.example.test/final-policy.pdf",
        )


class _RedirectSuccessAdapter:
    def __init__(self):
        self.calls = 0

    def fetch_document(self, document):
        self.calls += 1
        return FetchResult(
            ok=True,
            status=DownloadStatus.SUCCESS,
            content=b"%PDF-1.7\nnew response that must not be saved",
            content_type="application/pdf",
            original_filename="policy.pdf",
            http_status=200,
            final_url="https://cdn.example.test/final-policy.pdf",
        )


class _Errors:
    def record(self, **kwargs):
        return None


def test_redirect_uses_one_identity_key_for_pending_and_terminal(tmp_path):
    repository = FakeRepository()
    manifest = ManifestService(tmp_path, "RUN", repository=repository)
    service = DownloadService(
        config=None,
        paths=None,
        manifest=manifest,
        errors=_Errors(),
    )
    document = Document(
        DocumentType.POLICY,
        "약관",
        "https://origin.example.test/download?id=1",
    )

    adapter = _RedirectFailureAdapter()
    record = service.process_document(adapter, version(), document)

    assert [name for name, _ in repository.events] == ["seen", "result"]
    pending = repository.seen[0]
    terminal = repository.results[0]
    assert pending["file_status"] == "PENDING"
    assert pending["document_key"] == terminal["document_key"]
    assert record.document_url == "https://origin.example.test/download?id=1"
    # v2 identity는 fetch 전 원본 URL을 사용하고 final_url은 metadata다.
    assert terminal["document_key"] == document_key_for_manifest(record.to_row())


def test_redirect_rechecks_final_url_checkpoint_and_reuses_existing_file(tmp_path):
    repository = FakeRepository()
    paths = PathService(str(tmp_path), "output", target_month="2024-01")
    manifest = ManifestService(paths.output_root, "RUN", repository=repository)
    service = DownloadService(
        config=None,
        paths=paths,
        manifest=manifest,
        errors=_Errors(),
    )
    current_version = version()
    origin = Document(
        DocumentType.POLICY,
        "약관",
        "https://origin.example.test/download?id=1",
    )
    final_document = Document(
        DocumentType.POLICY,
        "약관",
        "https://cdn.example.test/final-policy.pdf",
    )
    final_record = service._base_record(current_version, final_document)
    saved = paths.output_root / "01_문서" / "DB손해보험" / "policy.pdf"
    saved.parent.mkdir(parents=True)
    content = b"%PDF-1.7\nexisting valid file"
    saved.write_bytes(content)
    final_record.download_status = DownloadStatus.SUCCESS
    final_record.saved_relative_path = saved.relative_to(paths.output_root).as_posix()
    final_record.sha256 = hashlib.sha256(content).hexdigest()
    final_record.file_size = len(content)
    manifest.previous[final_record.key()] = final_record.to_row()

    adapter = _RedirectSuccessAdapter()
    result = service.process_document(adapter, current_version, origin)

    assert adapter.calls == 0
    assert result.download_status == DownloadStatus.DUPLICATE_SKIPPED
    assert result.saved_relative_path == saved.relative_to(paths.output_root).as_posix()
    assert saved.read_bytes() == content
    assert [name for name, _ in repository.events] == ["seen", "result"]
    assert repository.seen[0]["document_key"] == repository.results[0]["document_key"]
    assert repository.results[0]["document_key"] == document_key_for_manifest(result.to_row())


def test_retry_failed_resolves_unique_legacy_redirect_failure(tmp_path):
    repository = FakeRepository()
    paths = PathService(str(tmp_path), "output", target_month="2024-01")
    manifest = ManifestService(paths.output_root, "RUN", repository=repository)
    service = DownloadService(
        config=None,
        paths=paths,
        manifest=manifest,
        errors=_Errors(),
        retry_failed_only=True,
    )
    current_version = version()
    origin = Document(
        DocumentType.POLICY,
        "약관",
        "https://origin.example.test/download?id=1",
    )
    failed_final = service._base_record(
        current_version,
        Document(
            DocumentType.POLICY,
            "약관",
            "https://cdn.example.test/final-policy.pdf",
        ),
    )
    failed_final.download_status = DownloadStatus.DOWNLOAD_FAILED
    manifest.previous[failed_final.key()] = failed_final.to_row()

    adapter = _RedirectFailureAdapter()
    result = service.process_document(adapter, current_version, origin)

    assert adapter.calls == 1
    assert result.download_status == DownloadStatus.DOWNLOAD_FAILED
    assert result.document_url == "https://origin.example.test/download?id=1"
    assert repository.results[0]["document_key"] == document_key_for_manifest(result.to_row())


def test_retry_failed_repairs_missing_file_under_legacy_final_url_key(tmp_path):
    repository = FakeRepository()
    paths = PathService(str(tmp_path), "output", target_month="2024-01")
    manifest = ManifestService(paths.output_root, "RUN", repository=repository)
    service = DownloadService(
        config=None,
        paths=paths,
        manifest=manifest,
        errors=_Errors(),
        retry_failed_only=True,
    )
    current_version = version()
    origin = Document(
        DocumentType.POLICY,
        "약관",
        "https://origin.example.test/download?id=1",
    )
    final_record = service._base_record(
        current_version,
        Document(
            DocumentType.POLICY,
            "약관",
            "https://cdn.example.test/final-policy.pdf",
        ),
    )
    final_record.download_status = DownloadStatus.SUCCESS
    final_record.saved_relative_path = "missing-policy.pdf"
    final_record.sha256 = "a" * 64
    manifest.previous[final_record.key()] = final_record.to_row()

    adapter = _RedirectFailureAdapter()
    result = service.process_document(adapter, current_version, origin)

    assert adapter.calls == 1
    assert result.download_status == DownloadStatus.DOWNLOAD_FAILED
    assert result.document_url == "https://origin.example.test/download?id=1"
    assert repository.results[0]["document_key"] == document_key_for_manifest(result.to_row())


class _FailureWithoutFinalUrlAdapter:
    def __init__(self):
        self.calls = 0

    def fetch_document(self, document):
        self.calls += 1
        return FetchResult(
            ok=False,
            status=DownloadStatus.DOWNLOAD_FAILED,
            reason="redirect 전 서버 오류",
            http_status=500,
        )


def test_redirect_failure_without_final_url_updates_unique_legacy_key(tmp_path):
    repository = FakeRepository()
    manifest = ManifestService(tmp_path, "RUN", repository=repository)
    service = DownloadService(
        config=None,
        paths=None,
        manifest=manifest,
        errors=_Errors(),
    )
    current_version = version()
    origin = Document(
        DocumentType.POLICY,
        "약관",
        "https://origin.example.test/download?id=1",
    )
    final_record = service._base_record(
        current_version,
        Document(
            DocumentType.POLICY,
            "약관",
            "https://cdn.example.test/final-policy.pdf",
        ),
    )
    final_record.download_status = DownloadStatus.DOWNLOAD_FAILED
    manifest.previous[final_record.key()] = final_record.to_row()

    adapter = _FailureWithoutFinalUrlAdapter()
    result = service.process_document(adapter, current_version, origin)

    assert adapter.calls == 1
    assert result.document_url == origin.document_url
    assert repository.results[0]["document_key"] == document_key_for_manifest(result.to_row())


def test_redirect_context_does_not_merge_checkpoint_plan_row(tmp_path):
    repository = FakeRepository()
    manifest = ManifestService(tmp_path, "RUN", repository=repository)
    service = DownloadService(
        config=None,
        paths=None,
        manifest=manifest,
        errors=_Errors(),
        retry_failed_only=True,
    )
    current_version = version()
    origin = Document(
        DocumentType.POLICY,
        "약관",
        "https://origin.example.test/download?id=1",
    )
    plan_record = service._base_record(
        current_version,
        Document(
            DocumentType.POLICY,
            "약관",
            "https://cdn.example.test/final-policy.pdf",
        ),
    )
    plan_record.checkpoint_key = "POST-plan-1"
    plan_record.download_status = DownloadStatus.DOWNLOAD_FAILED
    manifest.previous[plan_record.key()] = plan_record.to_row()

    adapter = _RedirectFailureAdapter()
    result = service.process_document(adapter, current_version, origin)

    assert adapter.calls == 0
    assert result.download_status == DownloadStatus.DUPLICATE_SKIPPED
    assert result.document_url == origin.document_url


def test_retry_failed_redownloads_completed_checkpoint_when_file_is_missing(tmp_path):
    repository = FakeRepository()
    paths = PathService(str(tmp_path), "documents", target_month="2024-01")
    manifest = ManifestService(paths.output_root, "RUN", repository=repository)
    service = DownloadService(
        config=None,
        paths=paths,
        manifest=manifest,
        errors=_Errors(),
        retry_failed_only=True,
    )
    current_version = version()
    document = Document(DocumentType.POLICY, "약관", "https://example.test/policy.pdf")
    probe = service._base_record(current_version, document)
    manifest.previous[probe.key()] = {
        **probe.to_row(),
        "download_status": DownloadStatus.SUCCESS,
        "saved_relative_path": "missing.pdf",
        "sha256": "a" * 64,
    }
    adapter = _RedirectFailureAdapter()

    record = service.process_document(adapter, current_version, document)

    assert adapter.calls == 1
    assert record.download_status == DownloadStatus.DOWNLOAD_FAILED


def test_retry_failed_new_skip_is_pending_not_available(tmp_path):
    repository = FakeRepository()
    manifest = ManifestService(tmp_path, "RUN", repository=repository)
    service = DownloadService(
        config=None,
        paths=None,
        manifest=manifest,
        errors=_Errors(),
        retry_failed_only=True,
    )
    adapter = _RedirectFailureAdapter()
    document = Document(DocumentType.POLICY, "약관", "https://example.test/policy.pdf")

    record = service.process_document(adapter, version(), document)

    assert adapter.calls == 0
    assert record.download_status == DownloadStatus.DUPLICATE_SKIPPED
    assert repository.results[0]["file_status"] == "PENDING"
    assert repository.results[0]["saved_relative_path"] is None
    assert repository.results[0]["sha256"] is None


class _PartialStatusRepository(FakeRepository):
    def update_status_rows_detailed(self, rows):
        self.status_payload = list(rows)
        return StatusUpdateResult(
            requested=len(self.status_payload),
            updated=max(0, len(self.status_payload) - 1),
            stale_noop=0,
            missing=1 if self.status_payload else 0,
        )


def _status_row(url: str) -> dict:
    return ManifestRecord(
        company_code="DB",
        company_name="DB손해보험",
        source_product_id="P1",
        product_name_raw="테스트상품",
        target_date="2024-01-01",
        document_type=DocumentType.POLICY,
        document_url=url,
        normalized_sale_status="ENDED",
        saved_relative_path=f"01_문서/{url.rsplit('/', 1)[-1]}",
    ).to_row()


def test_partial_status_update_is_not_written_to_outbox_and_raises(tmp_path):
    outbox = DatabaseOutbox(tmp_path / "db_outbox" / "DB.jsonl")
    repository = _PartialStatusRepository()
    service = ManifestService(
        tmp_path,
        "RUN",
        repository=repository,
        outbox=outbox,
    )
    rows = [
        _status_row("https://example.test/a.pdf"),
        _status_row("https://example.test/b.pdf"),
    ]

    with pytest.raises(RuntimeError, match="DB 판매상태 갱신 누락"):
        service.replace_previous_rows(rows)

    # 일부 key 누락은 재연결로 회복되지 않는 영구 데이터 오류다. 자동
    # replay poison을 만들지 않고 회사 실행을 fail-closed한다.
    assert outbox.pending() == []


def test_partial_status_outbox_replay_is_not_acknowledged(tmp_path):
    outbox = DatabaseOutbox(tmp_path / "db_outbox" / "DB.jsonl")
    outbox.append({
        "operation": "update_status_rows",
        "payload": [
                {"document_key": "DOC_" + "a" * 10, "sale_status": "ENDED"},
                {"document_key": "DOC_" + "b" * 10, "sale_status": "ENDED"},
        ],
    })
    repository = _PartialStatusRepository()

    with pytest.raises(RuntimeError, match="DB outbox 재생 실패"):
        CrawlerManager._replay_db_outbox(repository, outbox)

    assert len(outbox.pending()) == 1
    assert not outbox.ack_path.exists()
