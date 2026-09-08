from __future__ import annotations

from datetime import datetime, timezone

import pytest
import psycopg

from crawler.db_outbox import DatabaseOutbox, OutboxCorruptionError
from crawler.document_identity import (
    DOCUMENT_KEY_PREFIX,
    PRODUCT_VERSION_KEY_PREFIX,
    IDENTITY_VERSION,
    document_key_for_manifest,
    document_key_for_database_row,
    identity_for,
    manifest_identity_source,
    metadata_for,
    product_version_key_for_manifest,
    product_version_key_for_database_row,
    source_locator_for_document,
)
from crawler.document_repository import (
    DatabaseConfig,
    DisclosureDocumentRepository,
    DocumentPayload,
    normalize_source_metadata,
    payload_from_record,
)
from models.document import Document, DownloadStatus
from models.product_version import ProductVersion


def test_manifest_identity_is_compatible_with_legacy_key() -> None:
    class Row:
        company_code = "KB"
        source_product_id = "P-1"
        product_name_raw = "상품"
        target_date = "2025-01-01"
        document_type = "POLICY"
        document_url = ""
        original_filename = "약관.pdf"
        checkpoint_key = ""

    assert manifest_identity_source(Row()) == Row.company_code + "|P-1|상품|2025-01-01|POLICY|약관.pdf"
    document_value = document_key_for_manifest(Row())
    assert document_value.startswith(DOCUMENT_KEY_PREFIX)
    assert len(document_value) == 14
    assert document_value[len(DOCUMENT_KEY_PREFIX):].isalnum()
    assert document_key_for_manifest(
        {
            "company_code": Row.company_code,
            "source_product_id": Row.source_product_id,
            "product_name_raw": Row.product_name_raw,
            "target_date": Row.target_date,
            "document_type": Row.document_type,
            "document_url": Row.document_url,
            "original_filename": Row.original_filename,
            "checkpoint_key": Row.checkpoint_key,
        }
    ) == document_key_for_manifest(Row())


def test_redirect_final_url_does_not_change_document_identity() -> None:
    class Row:
        company_code = "KB"
        source_product_id = "P-1"
        product_name_raw = "상품"
        target_date = "2025-01-01"
        document_type = "POLICY"
        document_url = "https://origin.example/download?id=1"
        original_filename = ""
        source_locator = "https://origin.example/download?id=1"
        checkpoint_key = ""

    before = document_key_for_manifest(Row())
    Row.document_url = "https://cdn.example/files/policy.pdf"
    assert document_key_for_manifest(Row()) == before


def test_runtime_identity_matches_manifest_shaped_row() -> None:
    version = ProductVersion("KB", "KB손보", "상품", "https://example.test/detail")
    version.source_product_id = "P-1"
    version.sale_start_date = __import__("datetime").date(2025, 1, 1)
    document = Document("POLICY", "약관", "https://example.test/policy.pdf")

    class Record:
        company_code = "KB"
        source_product_id = "P-1"
        product_name_raw = "상품"
        target_date = "2025-01-01"
        document_date = "2025-01-01"
        document_type = "POLICY"
        document_url = document.document_url
        original_filename = ""
        source_locator = document.document_url
        checkpoint_key = ""
        sale_start_date = "2025-01-01"
        source_page_url = "https://example.test/detail"

    runtime = identity_for(version, document, Record())
    row = {
        "company_code": "KB",
        "source_product_id": "P-1",
        "product_name_raw": "상품",
        "target_date": "2025-01-01",
        "document_type": "POLICY",
        "document_url": document.document_url,
        "original_filename": "",
        "source_locator": document.document_url,
        "checkpoint_key": "",
        "sale_start_date": "2025-01-01",
        "source_page_url": "https://example.test/detail",
    }
    assert runtime.document_key == document_key_for_manifest(row)
    assert runtime.product_version_key == product_version_key_for_manifest(row)
    db_row = {
        "company_code": "KB",
        "source_product_id": "P-1",
        "product_name": "상품",
        "document_date": "2025-01-01",
        "sale_start_date": "2025-01-01",
        "source_page_url": "https://example.test/detail",
        "document_type": "POLICY",
        "document_url": document.document_url,
        "source_metadata": {"source_locator": document.document_url},
    }
    assert product_version_key_for_database_row(db_row) == runtime.product_version_key
    assert document_key_for_database_row(db_row) == runtime.document_key


def test_post_source_locator_excludes_secret_and_separates_attachments() -> None:
    first = Document(
        "POLICY", "약관", download_hint={
            "filePath": "/uploadwas/life/a/", "fileName": "policy.pdf",
            "token": "secret-token", "attachmentOrdinal": 1,
        }
    )
    second = Document(
        "POLICY", "약관", download_hint={
            "filePath": "/uploadwas/life/a/", "fileName": "policy.pdf",
            "token": "other-secret", "attachmentOrdinal": 2,
        }
    )
    assert "secret-token" not in source_locator_for_document(first)
    assert source_locator_for_document(first) != source_locator_for_document(second)


def test_relative_url_source_locator_excludes_sensitive_query() -> None:
    document = Document(
        "POLICY",
        "약관",
        "/download/policy?id=42&token=secret-token&api_key=secret-api-key&signature=secret-signature",
    )

    locator = source_locator_for_document(document)

    assert locator == "/download/policy?id=42"
    assert "secret-token" not in locator
    assert "secret-api-key" not in locator
    assert "secret-signature" not in locator


def test_query_only_secret_locator_falls_back_without_reusing_secret() -> None:
    with_filename = Document(
        "POLICY",
        "약관",
        "?token=secret-token",
        "policy.pdf",
    )
    without_filename = Document(
        "POLICY",
        "약관",
        "?token=other-secret-token",
    )

    assert source_locator_for_document(with_filename) == "policy.pdf"
    assert source_locator_for_document(without_filename) == "REDACTED_QUERY_LOCATOR"


def test_post_hint_nested_url_excludes_sensitive_query() -> None:
    document = Document(
        "POLICY",
        "약관",
        download_hint={
            "callbackUrl": "/download/policy?id=42&session=secret-session",
            "fileName": "policy.pdf",
        },
    )

    locator = source_locator_for_document(document)

    assert "secret-session" not in locator
    assert "/download/policy?id=42" in locator


def test_legacy_post_row_transitions_once_to_stable_v2_identity() -> None:
    """source_locator가 없던 v1 행과 v2 행은 전환 중 공존할 수 있다.

    v2 key는 이후 실행마다 동일해야 하므로 legacy 1행과 runtime 1행을
    넘어 계속 새 행이 생기지는 않는다.
    """
    legacy = {
        "company_code": "MIRAE_LIFE",
        "source_product_id": "P-1",
        "product_name_raw": "상품",
        "target_date": "2025-01-01",
        "document_type": "POLICY",
        "document_url": "",
        "original_filename": "policy.pdf",
        "source_locator": "",
        "checkpoint_key": "",
    }
    document = Document(
        "POLICY",
        "약관",
        original_filename="policy.pdf",
        download_hint={
            "filePath": "/upload/life/",
            "fileName": "policy.pdf",
            "attachmentOrdinal": 1,
        },
    )
    runtime = dict(legacy, source_locator=source_locator_for_document(document))

    legacy_key = document_key_for_manifest(legacy)
    first_runtime_key = document_key_for_manifest(runtime)
    second_runtime_key = document_key_for_manifest(dict(runtime))

    assert first_runtime_key != legacy_key
    assert first_runtime_key == second_runtime_key
    assert len({legacy_key, first_runtime_key, second_runtime_key}) == 2
    metadata = metadata_for(
        ProductVersion("MIRAE_LIFE", "미래에셋생명", "상품", "https://example.test"),
        document,
        runtime,
    )
    assert "identity_version" not in metadata
    assert "document_key" not in metadata
    assert "product_version_key" not in metadata


def test_source_metadata_normalization_preserves_migration_provenance() -> None:
    original = {
        "document_key": "DOC_A000000001",
        "product_version_key": "PROD_VER_B000000001",
        "identity_version": 4,
        "migration": {"source": "manifest.csv", "source_row": 2},
        "checkpoint_key": "legacy-checkpoint",
        "source_locator": "https://example.test/doc",
    }
    normalized = normalize_source_metadata(original)
    assert normalized == {
        "migration": {"source": "manifest.csv", "source_row": 2},
        "checkpoint_key": "legacy-checkpoint",
        "source_locator": "https://example.test/doc",
    }
    assert original["document_key"] == "DOC_A000000001"


def test_final_url_is_metadata_only() -> None:
    version = ProductVersion("KB", "KB손보", "상품", "https://example.test")
    document = Document("POLICY", "약관", "https://origin.test/download?id=1")

    class Record:
        company_code = "KB"
        source_product_id = "P1"
        product_name_raw = "상품"
        target_date = "2025-01-01"
        document_type = "POLICY"
        document_url = document.document_url
        source_locator = document.document_url
        original_filename = ""
        checkpoint_key = ""
        final_url = "https://cdn.test/policy.pdf"

    metadata = metadata_for(version, document, Record())
    assert metadata["source_locator"] == document.document_url
    assert metadata["final_url"] == Record.final_url


def test_version_key_uses_manifest_common_fields() -> None:
    row = {
        "company_code": "KB",
        "source_product_id": "P-1",
        "product_name_raw": "상품",
        "sale_start_date": "2025-01-01",
        "target_date": "2025-01-01",
        "source_page_url": "https://example.test/detail",
    }
    product_value = product_version_key_for_manifest(row)
    assert product_value.startswith(PRODUCT_VERSION_KEY_PREFIX)
    assert len(product_value) == 19
    assert product_value[len(PRODUCT_VERSION_KEY_PREFIX):].isalnum()


def test_sensitive_download_hints_are_removed() -> None:
    version = ProductVersion("KB", "KB손보", "상품", "https://example.test")
    doc = Document(
        "POLICY",
        "약관",
        download_hint={"params": {"productCode": "P1", "token": "secret"}, "headers": {"Cookie": "x"}},
    )
    metadata = metadata_for(version, doc)
    assert metadata["download_hint"] == {"params": {"productCode": "P1"}, "headers": {}}


def test_checkpoint_metadata_preserves_legacy_identity_whitespace() -> None:
    version = ProductVersion("KB", "KB손보", "상품", "https://example.test")
    document = Document("POLICY", "약관", "https://example.test/doc")

    class Record:
        checkpoint_key = "  legacy-plan  "

    metadata = metadata_for(version, document, Record())

    assert metadata["checkpoint_key"] == "  legacy-plan  "


def test_no_document_link_still_has_stable_identity() -> None:
    version = ProductVersion("KB", "KB손보", "상품", "https://example.test")

    class Record:
        company_code = "KB"
        company_name = "KB손보"
        product_name_raw = "상품"
        product_name_normalized = "상품"
        source_product_id = "P1"
        target_date = "2025-01-01"
        document_date = "2025-01-01"
        document_type = ""
        document_label = ""
        document_url = ""
        original_filename = ""
        checkpoint_key = ""
        download_status = "NO_DOCUMENT_LINK"
        run_id = "run-1"

    payload = payload_from_record(Record(), version=version, document=None)
    assert payload["document_key"].startswith(DOCUMENT_KEY_PREFIX)
    assert len(payload["document_key"]) == 14
    assert payload["product_version_key"].startswith(PRODUCT_VERSION_KEY_PREFIX)
    assert len(payload["product_version_key"]) == 19
    assert payload["document_key"] == document_key_for_database_row(payload)
    assert payload["document_type"] is None


def test_dry_run_is_pending_and_does_not_claim_download_run() -> None:
    class Record:
        company_code = "KB"
        company_name = "KB손보"
        product_name_raw = "상품"
        product_name_normalized = "상품"
        source_product_id = "P1"
        target_date = "2025-01-01"
        document_type = "POLICY"
        download_status = "DRY_RUN"
        run_id = "run-1"
        checkpoint_key = ""
        document_url = "https://example.test/doc"
        original_filename = "doc.pdf"

    version = ProductVersion("KB", "KB손보", "상품", "https://example.test")
    payload = payload_from_record(Record(), version=version, document=None)
    assert payload["file_status"] == "PENDING"
    assert payload["last_download_run_id"] is None


@pytest.mark.parametrize(
    ("saved_relative_path", "sha256", "expected"),
    [
        ("", "", "PENDING"),
        ("01_문서/DB/약관.pdf", "", "AVAILABLE"),
        ("", "a" * 64, "AVAILABLE"),
    ],
)
def test_duplicate_without_file_evidence_is_not_available(
    saved_relative_path, sha256, expected
) -> None:
    class Record:
        company_code = "DB"
        company_name = "DB손해보험"
        product_name_raw = "상품"
        product_name_normalized = "상품"
        source_product_id = "P1"
        target_date = "2025-01-01"
        document_type = "POLICY"
        download_status = DownloadStatus.DUPLICATE_SKIPPED
        run_id = "run-1"
        checkpoint_key = ""
        document_url = "https://example.test/doc"
        original_filename = "doc.pdf"

    record = Record()
    record.saved_relative_path = saved_relative_path
    record.sha256 = sha256
    version = ProductVersion("DB", "DB손해보험", "상품", "https://example.test")

    payload = payload_from_record(record, version=version, document=None)

    assert payload["file_status"] == expected
    if expected == "PENDING":
        assert payload["downloaded_at"] is None
        assert payload["last_download_run_id"] is None


def test_success_without_file_evidence_is_unavailable() -> None:
    class Record:
        company_code = "DB"
        company_name = "DB손해보험"
        product_name_raw = "상품"
        product_name_normalized = "상품"
        source_product_id = "P1"
        target_date = "2025-01-01"
        document_type = "POLICY"
        download_status = DownloadStatus.SUCCESS
        downloaded_at = "2026-08-24T01:00:00+00:00"
        run_id = "run-1"
        checkpoint_key = ""
        document_url = "https://example.test/doc"
        original_filename = "doc.pdf"
        saved_relative_path = ""
        sha256 = ""

    version = ProductVersion("DB", "DB손해보험", "상품", "https://example.test")
    payload = payload_from_record(Record(), version=version, document=None)

    assert payload["file_status"] == "UNAVAILABLE"
    assert payload["downloaded_at"] is None
    assert payload["last_download_run_id"] is None


class _FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _FakeCursor:
    def __init__(self):
        self.calls = []
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _FakeConnection(_FakeCursor):
    closed = False

    def transaction(self):
        return _FakeTransaction()

    def close(self):
        self.closed = True


def test_repository_reuses_connection_and_emits_upsert() -> None:
    created = []

    def factory(**kwargs):
        connection = _FakeConnection()
        created.append((connection, kwargs))
        return connection

    repository = DisclosureDocumentRepository(
        DatabaseConfig("host", 5432, "user", "password", "db"),
        connection_factory=factory,
    )
    now = datetime.now(timezone.utc)
    payload = DocumentPayload(
        document_key="DOC_A000000001",
        product_version_key="PROD_VER_B000000001",
        company_code="KB",
        company_name="KB손해보험",
        product_name="상품",
        product_name_normalized="상품",
        last_attempt_at=now,
        last_seen_at=now,
    )
    repository.upsert_seen(payload)
    repository.upsert_result(payload)
    assert len(created) == 1
    assert len(created[0][0].calls) == 2
    assert "INSERT INTO rs_disclosure_documents AS rs" in created[0][0].calls[0][0]
    assert "ON CONFLICT (document_key)" in created[0][0].calls[0][0]
    assert "EXCLUDED.last_attempt_status='DRY_RUN'" in created[0][0].calls[1][0]
    assert "EXCLUDED.last_download_run_id IS NOT NULL" in created[0][0].calls[1][0]
    assert "EXCLUDED.last_status_run_id IS NOT NULL" in created[0][0].calls[1][0]
    assert "rs.file_status='AVAILABLE' AND EXCLUDED.file_status <> 'AVAILABLE'" not in created[0][0].calls[1][0]
    assert "EXCLUDED.last_attempt_status='DRY_RUN' AND rs.file_status='AVAILABLE' THEN rs.saved_relative_path" in created[0][0].calls[1][0]


def test_upsert_stale_event_guards_discovery_and_document_fields() -> None:
    connection = _FakeConnection()
    repository = DisclosureDocumentRepository(
        DatabaseConfig("host", 5432, "user", "password", "db"),
        connection_factory=lambda **_: connection,
    )
    now = datetime.now(timezone.utc)
    payload = DocumentPayload(
        document_key="DOC_A000000001",
        product_version_key="PROD_VER_B000000001",
        company_code="KB",
        company_name="KB손해보험",
        product_name="상품",
        product_name_normalized="상품",
        document_url="https://example.test/document.pdf",
        last_attempt_at=now,
        last_seen_at=now,
    )

    repository.upsert_seen(payload)
    seen_sql = connection.calls[-1][0]
    newer_seen = "(rs.last_seen_at IS NULL OR EXCLUDED.last_seen_at >= rs.last_seen_at)"
    newer_status = "(rs.status_checked_at IS NULL OR (EXCLUDED.status_checked_at IS NOT NULL AND EXCLUDED.status_checked_at >= rs.status_checked_at))"
    newer_status_event = f"({newer_seen} AND {newer_status})"
    assert f"product_name=CASE WHEN {newer_seen} THEN EXCLUDED.product_name ELSE rs.product_name END" in seen_sql
    assert f"sale_start_date=CASE WHEN {newer_status_event} THEN EXCLUDED.sale_start_date ELSE rs.sale_start_date END" in seen_sql
    assert f"source_metadata=CASE WHEN {newer_seen}" in seen_sql
    assert "jsonb_build_object('migration', rs.source_metadata->'migration')" in seen_sql
    assert "jsonb_build_object('checkpoint_key', rs.source_metadata->'checkpoint_key')" in seen_sql
    assert "jsonb_build_object('source_locator', rs.source_metadata->'source_locator')" in seen_sql
    assert f"identity_version=CASE WHEN {newer_seen} THEN EXCLUDED.identity_version ELSE rs.identity_version END" in seen_sql

    repository.upsert_result(payload)
    result_sql = connection.calls[-1][0]
    newer_attempt = "(rs.last_attempt_at IS NULL OR EXCLUDED.last_attempt_at >= rs.last_attempt_at)"
    newer_result = f"({newer_attempt} OR {newer_seen})"
    assert f"product_name=CASE WHEN {newer_seen} THEN EXCLUDED.product_name ELSE rs.product_name END" in result_sql
    assert f"sale_end_date=CASE WHEN {newer_status_event} THEN EXCLUDED.sale_end_date ELSE rs.sale_end_date END" in result_sql
    assert f"source_metadata=CASE WHEN {newer_seen}" in result_sql
    assert f"document_url=CASE WHEN {newer_result} THEN COALESCE(EXCLUDED.document_url, rs.document_url) ELSE rs.document_url END" in result_sql
    assert f"identity_version=CASE WHEN {newer_result} THEN EXCLUDED.identity_version ELSE rs.identity_version END" in result_sql


def test_status_update_detailed_reports_handled_and_missing() -> None:
    connection = _FakeConnection()
    repository = DisclosureDocumentRepository(
        DatabaseConfig("host", 5432, "user", "password", "db"),
        connection_factory=lambda **_: connection,
    )
    result = repository.update_status_rows_detailed(
        [{"document_key": "DOC_A000000001", "sale_status": "ENDED", "status_checked_at": datetime.now(timezone.utc)}]
    )
    assert result.requested == 1
    assert result.handled == 1
    assert result.updated == 1
    assert result.stale_noop == 0
    assert result.missing == 0
    assert "WHERE document_key=%s" in connection.calls[-1][0]


class _ZeroUpdateConnection(_FakeConnection):
    def __init__(self, *, exists: bool):
        super().__init__()
        self._exists = exists
        self._selected = False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self._selected = "SELECT 1 FROM" in sql
        self.rowcount = 1 if self._selected and self._exists else 0
        return self

    def fetchone(self):
        return (1,) if self._selected and self._exists else None


@pytest.mark.parametrize(
    ("exists", "stale_noop", "missing"),
    [(True, 1, 0), (False, 0, 1)],
)
def test_status_update_detailed_distinguishes_stale_noop_and_missing(
    exists, stale_noop, missing
) -> None:
    connection = _ZeroUpdateConnection(exists=exists)
    repository = DisclosureDocumentRepository(
        DatabaseConfig("host", 5432, "user", "password", "db"),
        connection_factory=lambda **_: connection,
    )

    result = repository.update_status_rows_detailed([
        {
            "document_key": "DOC_A000000001",
            "sale_status": "ENDED",
            "status_checked_at": datetime.now(timezone.utc),
        }
    ])

    assert result.requested == 1
    assert result.updated == 0
    assert result.stale_noop == stale_noop
    assert result.missing == missing
    assert result.handled == stale_noop
    assert any("SELECT 1 FROM" in sql for sql, _ in connection.calls)


def test_outbox_replays_only_unacknowledged_events(tmp_path) -> None:
    outbox = DatabaseOutbox(tmp_path / "db_events.jsonl")
    outbox.append({"document_key": "a"})
    outbox.append({"document_key": "b"})
    received = []
    first = outbox.replay(lambda event: received.append(event), max_events=1)
    second = outbox.replay(lambda event: received.append(event))
    assert first == {"attempted": 1, "succeeded": 1, "failed": 0}
    assert second == {"attempted": 1, "succeeded": 1, "failed": 0}
    assert [event["document_key"] for event in received] == ["a", "b"]


def test_outbox_corruption_stops_replay(tmp_path) -> None:
    path = tmp_path / "db_events.jsonl"
    path.write_text('{"event_id":"broken",', encoding="utf-8")
    with pytest.raises(OutboxCorruptionError):
        DatabaseOutbox(path).replay(lambda _: None)


def test_outbox_stops_at_first_failure_and_preserves_fifo_order(tmp_path) -> None:
    outbox = DatabaseOutbox(tmp_path / "db_events.jsonl")
    outbox.append({"document_key": "a"})
    outbox.append({"document_key": "b"})
    attempted = []

    def fail_first(event):
        attempted.append(event["document_key"])
        raise RuntimeError("DB unavailable")

    failed = outbox.replay(fail_first)

    assert failed == {"attempted": 1, "succeeded": 0, "failed": 1}
    assert attempted == ["a"]
    assert len(outbox.pending()) == 2

    replayed = []
    recovered = outbox.replay(lambda event: replayed.append(event["document_key"]))
    assert recovered == {"attempted": 2, "succeeded": 2, "failed": 0}
    assert replayed == ["a", "b"]
