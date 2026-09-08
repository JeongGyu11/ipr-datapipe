from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import threading

import psycopg
import pytest

from crawler.crawler_manager import CrawlerManager
from crawler.db_outbox import (
    DatabaseOutbox,
    OutboxEventValidationError,
    is_transient_database_error,
)
from crawler.document_repository import (
    DatabaseConfig,
    DisclosureDocumentRepository,
    StatusUpdateResult,
)
from crawler.manifest_service import ManifestRecord, ManifestService
from models.document import DocumentType, DownloadStatus


def _db_event(operation: str = "upsert_result") -> dict:
    return {
        "operation": operation,
        "payload": {
            "document_key": "DOC_A000000001",
            "product_version_key": "PROD_VER_B000000001",
        },
    }


def test_outbox_rejects_invalid_operation_payload_before_write(tmp_path) -> None:
    outbox = DatabaseOutbox(tmp_path / "DB.jsonl")

    with pytest.raises(OutboxEventValidationError, match="document_key"):
        outbox.append({"operation": "upsert_result", "payload": {"document_key": "short"}})

    assert not outbox.path.exists()


def test_outbox_rejects_pre_cutover_raw_key_after_prefix_migration(tmp_path) -> None:
    outbox = DatabaseOutbox(tmp_path / "DB.jsonl")

    with pytest.raises(OutboxEventValidationError, match="document_key"):
        outbox.append(
            {
                "operation": "upsert_result",
                "payload": {
                    "document_key": "A000000001",
                    "product_version_key": "B000000001",
                },
            }
        )

    assert not outbox.path.exists()


def test_only_connection_errors_are_transient() -> None:
    assert is_transient_database_error(psycopg.OperationalError("connection closed"))
    assert is_transient_database_error(psycopg.InterfaceError("connection closed"))
    assert not is_transient_database_error(psycopg.IntegrityError("constraint"))
    assert not is_transient_database_error(ValueError("bad payload"))


def test_outbox_failure_is_audited_and_manual_quarantine_keeps_source(tmp_path) -> None:
    outbox = DatabaseOutbox(tmp_path / "DB.jsonl")
    event_id = outbox.append(_db_event())

    result = outbox.replay(lambda _: (_ for _ in ()).throw(ValueError("bad payload")))

    assert result == {"attempted": 1, "succeeded": 0, "failed": 1}
    assert '"failure_kind":"PERMANENT"' in outbox.failure_path.read_text(encoding="utf-8")
    original = outbox.path.read_bytes()

    outbox.quarantine(event_id, reason="schema 조사 완료", approved_by="run-1@host:123")

    assert outbox.pending() == []
    assert outbox.path.read_bytes() == original
    assert event_id in outbox.quarantine_audit_path.read_text(encoding="utf-8")


def test_outbox_compaction_drops_only_acknowledged_events(tmp_path) -> None:
    outbox = DatabaseOutbox(tmp_path / "DB.jsonl")
    first = outbox.append(_db_event())
    second = outbox.append(_db_event())
    third = outbox.append(_db_event())
    outbox._ack(first)
    outbox.quarantine(third, reason="영구 오류", approved_by="run-1@host:123")

    result = outbox.compact()

    assert result == {"before": 3, "removed": 1, "retained": 2}
    assert [item["event_id"] for item in outbox.pending()] == [second]
    source = outbox.path.read_text(encoding="utf-8")
    assert first not in source
    assert second in source
    assert third in source
    assert not outbox.ack_path.exists()
    assert third in outbox.quarantine_audit_path.read_text(encoding="utf-8")
    assert '"removed":1' in outbox.compaction_audit_path.read_text(encoding="utf-8")


def test_outbox_replay_compacts_when_threshold_is_reached(tmp_path) -> None:
    outbox = DatabaseOutbox(tmp_path / "DB.jsonl")
    outbox.append(_db_event())

    result = outbox.replay(lambda _event: None)
    compacted = outbox.compact_if_needed(data_bytes=0, ack_bytes=0)

    assert result == {"attempted": 1, "succeeded": 1, "failed": 0}
    assert compacted == {"before": 1, "removed": 1, "retained": 0}
    assert outbox.pending() == []


def test_manager_compacts_ack_only_outbox_before_early_return() -> None:
    class AckOnlyOutbox:
        compacted = False

        @staticmethod
        def pending():
            return []

        def compact_if_needed(self):
            self.compacted = True

    outbox = AckOnlyOutbox()

    CrawlerManager._replay_db_outbox(object(), outbox)

    assert outbox.compacted


def test_outbox_rejects_duplicate_explicit_event_id(tmp_path) -> None:
    outbox = DatabaseOutbox(tmp_path / "DB.jsonl")
    outbox.append(_db_event(), event_id="fixed-event")

    with pytest.raises(OutboxEventValidationError, match="중복"):
        outbox.append(_db_event(), event_id="fixed-event")


def test_outbox_serializes_concurrent_explicit_event_id_append(tmp_path) -> None:
    outbox = DatabaseOutbox(tmp_path / "DB.jsonl")
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def append_same_id() -> None:
        barrier.wait(timeout=5)
        try:
            outcomes.append(outbox.append(_db_event(), event_id="race-event"))
        except OutboxEventValidationError:
            outcomes.append("duplicate")

    workers = [threading.Thread(target=append_same_id) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=5)

    assert all(not worker.is_alive() for worker in workers)
    assert outcomes.count("race-event") == 1
    assert outcomes.count("duplicate") == 1
    assert [item["event_id"] for item in outbox.pending()] == ["race-event"]


def test_outbox_append_waits_for_compaction_and_is_not_lost(tmp_path, monkeypatch) -> None:
    outbox = DatabaseOutbox(tmp_path / "DB.jsonl")
    first = outbox.append(_db_event())
    outbox._ack(first)
    entered = threading.Event()
    release = threading.Event()
    original_entries = outbox._entries

    def paused_entries():
        entered.set()
        assert release.wait(timeout=5)
        return original_entries()

    monkeypatch.setattr(outbox, "_entries", paused_entries)
    compact_thread = threading.Thread(target=outbox.compact)
    compact_thread.start()
    assert entered.wait(timeout=5)
    appended = []
    append_thread = threading.Thread(target=lambda: appended.append(outbox.append(_db_event())))
    append_thread.start()
    release.set()
    compact_thread.join(timeout=5)
    append_thread.join(timeout=5)

    assert not compact_thread.is_alive()
    assert not append_thread.is_alive()
    assert [item["event_id"] for item in outbox.pending()] == appended


def test_pending_without_attempt_is_retryable_after_previous_run(tmp_path) -> None:
    service = ManifestService(tmp_path, "RUN")
    row = {
        "company_code": "DB",
        "product_name": "상품",
        "product_name_normalized": "상품",
        "document_type": DocumentType.POLICY,
        "document_date": date(2026, 6, 1),
        "file_status": "PENDING",
        "last_attempt_status": None,
    }

    projected = service._db_row_to_checkpoint(row)

    assert projected["download_status"] == DownloadStatus.DOWNLOAD_FAILED


def test_connection_factory_typeerror_is_not_retried_as_legacy_signature() -> None:
    calls = 0

    def fail_inside_factory(**_kwargs):
        nonlocal calls
        calls += 1
        raise TypeError("factory internal failure")

    repository = DisclosureDocumentRepository(
        DatabaseConfig("host", 5432, "user", "password", "db"),
        connection_factory=fail_inside_factory,
    )

    with pytest.raises(TypeError, match="factory internal failure"):
        _ = repository.connection

    assert calls == 1


class _Transaction:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _StatusConnection:
    closed = False

    def __init__(self, outcomes: list[str]):
        self.outcomes = iter(outcomes)
        self.rowcount = 0
        self._exists = False

    def transaction(self):
        return _Transaction()

    def execute(self, sql, params=None):
        if "UPDATE rs_disclosure_documents" in sql:
            outcome = next(self.outcomes)
            self.rowcount = 1 if outcome == "updated" else 0
            self._exists = outcome == "stale"
        elif "SELECT 1 FROM" in sql:
            self.rowcount = 1 if self._exists else 0
        return self

    def fetchone(self):
        return (1,) if self._exists else None

    def close(self):
        self.closed = True


def test_status_update_distinguishes_updated_stale_and_missing() -> None:
    connection = _StatusConnection(["updated", "stale", "missing"])
    repository = DisclosureDocumentRepository(
        DatabaseConfig("host", 5432, "user", "password", "db"),
        connection_factory=lambda **_: connection,
    )
    checked_at = datetime.now(timezone.utc)
    rows = [
        {
            "document_key": character.upper() + "000000000",
            "sale_status": "ENDED",
            "status_checked_at": checked_at + timedelta(seconds=index),
        }
        for index, character in enumerate(("a", "b", "c"))
    ]

    result = repository.update_status_rows_detailed(rows)

    assert result == StatusUpdateResult(requested=3, updated=1, stale_noop=1, missing=1)
    assert result.handled == 2


class _MissingStatusApiRepository:
    pass


def test_missing_status_update_api_fails_closed(tmp_path) -> None:
    service = ManifestService(tmp_path, "RUN", repository=_MissingStatusApiRepository())
    row = ManifestRecord(
        company_code="DB",
        company_name="DB손해보험",
        source_product_id="P1",
        product_name_raw="상품",
        target_date="2026-06-01",
        document_type=DocumentType.POLICY,
        document_url="https://example.test/policy.pdf",
        normalized_sale_status="ENDED",
    ).to_row()

    with pytest.raises(AttributeError, match="update_status_rows_detailed"):
        service.replace_previous_rows([row])


class _DetailedStatusRepository:
    def __init__(self, result: StatusUpdateResult):
        self.result = result

    def update_status_rows_detailed(self, _rows):
        return self.result


def test_outbox_replay_does_not_ack_missing_status_key(tmp_path) -> None:
    outbox = DatabaseOutbox(tmp_path / "DB.jsonl")
    event = _db_event("update_status_rows")
    event["payload"] = [event["payload"]]
    outbox.append(event)
    repository = _DetailedStatusRepository(
        StatusUpdateResult(requested=1, updated=0, stale_noop=0, missing=1)
    )

    with pytest.raises(RuntimeError, match="DB outbox 재생 실패"):
        CrawlerManager._replay_db_outbox(repository, outbox)

    assert len(outbox.pending()) == 1
