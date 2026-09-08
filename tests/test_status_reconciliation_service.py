from datetime import date
from pathlib import Path

from crawler.status_reconciliation_service import (
    active_manifest_rows,
    observations_from_versions,
    product_version_matches_row,
    RenameJournal,
    RenameEvent,
    StatusFolderMover,
    StatusObservation,
    StatusReconciliationService,
    logical_version_key,
    normalize_sale_state,
    status_prefixed_path,
)
from models.product_version import ProductVersion
from models.sale_status import SaleStatus


def row(*, status="판매중", path="DB손해보험/2024/01/판매중__20240101_상품/약관.pdf", filename="약관.pdf"):
    value = {
        "company_code": "DB",
        "source_product_id": "p-1",
        "sale_start_date": "2024-01-01",
        "target_date": "2024-01-01",
        "product_name_raw": "상품",
        "product_name_normalized": "상품",
        "sale_status": status,
        "saved_relative_path": path,
        "saved_filename": filename,
    }
    return value


def test_state_normalization_and_double_underscore_prefix():
    assert normalize_sale_state("판매중") == SaleStatus.ACTIVE
    assert normalize_sale_state("판매중지") == SaleStatus.ENDED
    assert normalize_sale_state("anything") == SaleStatus.UNKNOWN
    assert status_prefixed_path("DB/2024/01/20240101_상품", SaleStatus.ACTIVE).endswith(
        "판매중__20240101_상품"
    )


def test_active_rows_are_deduped_by_logical_version():
    first = row()
    second = dict(first, document_type="상품요약서", saved_filename="상품요약서.pdf")
    ended = row(status="판매중지")
    ended["source_product_id"] = "p-2"
    rows = active_manifest_rows([first, second, ended], "DB")
    assert len(rows) == 1
    assert logical_version_key(rows[0]) == logical_version_key(first)


def test_active_rows_prefer_saved_relative_path_representative_over_no_link_row():
    no_link = row(path="", filename="")
    no_link["download_status"] = "NO_DOCUMENT_LINK"
    saved = dict(row(), document_type="약관", saved_filename="약관.pdf")
    rows = active_manifest_rows([no_link, saved], "DB")
    assert len(rows) == 1
    assert rows[0]["saved_relative_path"] == saved["saved_relative_path"]


def test_product_versions_build_observation_for_same_id_and_sale_period():
    manifest_row = row()
    matching = ProductVersion(
        company_code="DB",
        company_name="DB손해보험",
        product_name_raw="상품",
        source_page_url="https://example.test",
        source_product_id="p-1",
        sale_status="판매중지",
        sale_start_date=date(2024, 1, 1),
        sale_end_date=date(2026, 7, 31),
    )
    other_period = ProductVersion(
        company_code="DB",
        company_name="DB손해보험",
        product_name_raw="상품",
        source_page_url="https://example.test",
        source_product_id="p-1",
        sale_status="판매중",
        sale_start_date=date(2025, 1, 1),
    )
    assert product_version_matches_row(matching, manifest_row)
    assert not product_version_matches_row(other_period, manifest_row)
    observations = observations_from_versions(
        [manifest_row], [other_period, matching], coverage_complete=True, source="DB.Step4"
    )
    observation = observations[logical_version_key(manifest_row)]
    assert observation.normalized_state == SaleStatus.ENDED
    assert observation.raw_status == "판매중지"
    assert observation.sale_end_date == date(2026, 7, 31)
    assert observation.source == "DB.Step4"
    assert status_prefixed_path("DB/2024/01/판매중__20240101_상품", SaleStatus.ENDED).endswith(
        "판매완료__20240101_상품"
    )


def test_conflicting_duplicate_status_observations_are_unusable():
    manifest_row = row()
    active = ProductVersion(
        company_code="DB", company_name="DB손해보험", product_name_raw="상품",
        source_page_url="https://example.test", source_product_id="p-1",
        sale_status="판매중", sale_start_date=date(2024, 1, 1),
    )
    ended = ProductVersion(
        company_code="DB", company_name="DB손해보험", product_name_raw="상품",
        source_page_url="https://example.test", source_product_id="p-1",
        sale_status="판매중지", sale_start_date=date(2024, 1, 1),
        sale_end_date=date(2026, 7, 31),
    )
    observation = observations_from_versions(
        [manifest_row], [active, ended], coverage_complete=True
    )[logical_version_key(manifest_row)]
    assert observation.usable is False
    result = StatusReconciliationService().reconcile(
        [manifest_row], {logical_version_key(manifest_row): observation}
    )
    assert result.updated_rows == [manifest_row]
    assert result.actions == []


def test_active_to_ended_updates_all_document_rows_without_download():
    first = row()
    second = dict(first, document_type="상품요약서", saved_filename="상품요약서.pdf", saved_relative_path="DB손해보험/2024/01/판매중__20240101_상품/상품요약서.pdf")
    key = logical_version_key(first)
    result = StatusReconciliationService().reconcile(
        [first, second],
        {key: StatusObservation(SaleStatus.ENDED, raw_status="판매중지", sale_end_date="2026-07-31", source="detail")},
    )
    assert result.stats["ended"] == 1
    assert result.actions[0].move_required is True
    assert all(item["sale_status"] == "판매중지" for item in result.updated_rows)
    assert all(item["normalized_sale_status"] == "ENDED" for item in result.updated_rows)
    assert all(item["status_changed_at"] == result.updated_rows[0]["status_changed_at"] for item in result.updated_rows)
    assert all("판매완료__20240101_상품" in item["saved_relative_path"] for item in result.updated_rows)
    # No download instruction/state is created by this service.
    assert all("download_status" not in item for item in result.updated_rows)


def test_still_active_legacy_folder_gets_current_prefix():
    item = row(path="DB손해보험/2024/01/20240101_상품/약관.pdf")
    key = logical_version_key(item)
    result = StatusReconciliationService().reconcile(
        [item], {key: StatusObservation(SaleStatus.ACTIVE, raw_status="판매중")}
    )
    assert result.actions[0].move_required is True
    assert "판매중__20240101_상품" in result.updated_rows[0]["saved_relative_path"]


def test_first_missing_has_grace_and_second_missing_becomes_unknown():
    item = row()
    key = logical_version_key(item)
    service = StatusReconciliationService()
    first = service.reconcile([item], {}, company_coverage={"DB": True})
    assert first.updated_rows[0]["sale_status"] == "판매중"
    assert first.updated_rows[0]["status_missing_count"] == 1
    assert "status_changed_at" not in first.updated_rows[0]
    second = service.reconcile(first.updated_rows, {}, company_coverage={"DB": True})
    assert second.updated_rows[0]["sale_status"] == "판매중"
    assert second.updated_rows[0]["normalized_sale_status"] == "UNKNOWN"
    assert second.updated_rows[0]["status_missing_count"] == 2
    assert second.actions[0].reason == "consecutive_complete_absence"


def test_partial_or_failed_coverage_does_not_mutate():
    item = row()
    key = logical_version_key(item)
    result = StatusReconciliationService().reconcile(
        [item],
        {key: StatusObservation(SaleStatus.ENDED, coverage_complete=False, request_ok=True)},
        company_coverage={"DB": False},
    )
    assert result.updated_rows == [item]
    assert result.actions == []


def test_explicit_status_can_correct_unknown_back_to_active():
    item = row(status="상태미상", path="DB/2024/01/상태미상__20240101_상품")
    key = logical_version_key(item)
    result = StatusReconciliationService().reconcile(
        [item], {key: StatusObservation(SaleStatus.ACTIVE, raw_status="판매중")}
    )
    assert result.updated_rows[0]["sale_status"] == "판매중"
    assert result.updated_rows[0]["normalized_sale_status"] == "ACTIVE"
    assert "판매중__" in result.updated_rows[0]["saved_relative_path"]


def test_rename_journal_recovers_after_process_dies_after_rename(tmp_path: Path):
    source = tmp_path / "판매중__상품"
    destination = tmp_path / "판매완료__상품"
    source.mkdir()
    (source / "a.pdf").write_bytes(b"same")
    journal = RenameJournal(tmp_path / "99_운영" / "state" / "status_moves.jsonl")
    mover = StatusFolderMover(journal, documents_root=tmp_path)
    # Simulate a crash after the physical move but before MOVED/COMMITTED.
    journal.append(RenameEvent("x", "PLANNED", str(source), str(destination), "now"))
    source.rename(destination)
    recovered = mover.recover()
    assert recovered[0].phase == "MOVED"
    assert destination.exists()
    assert mover.finalize(recovered[0]) is True
    assert mover.recover() == []


def test_collision_never_overwrites_and_allocates_suffix(tmp_path: Path):
    source = tmp_path / "판매중__상품"
    destination = tmp_path / "판매완료__상품"
    source.mkdir(); destination.mkdir()
    (source / "a.pdf").write_bytes(b"new")
    (destination / "a.pdf").write_bytes(b"old")
    mover = StatusFolderMover(RenameJournal(tmp_path / "moves.jsonl"), documents_root=tmp_path)
    moved = mover.move(source, destination)
    assert moved.phase == "MOVED"
    assert moved.destination.name == "판매완료__상품_2"
    assert (destination / "a.pdf").read_bytes() == b"old"
    assert (moved.destination / "a.pdf").read_bytes() == b"new"
    assert mover.finalize(moved) is True


def test_identical_collision_is_conflict_without_deleting_source(tmp_path: Path):
    source = tmp_path / "판매중__상품"
    destination = tmp_path / "판매완료__상품"
    source.mkdir(); destination.mkdir()
    (source / "a.pdf").write_bytes(b"same")
    (destination / "a.pdf").write_bytes(b"same")
    mover = StatusFolderMover(RenameJournal(tmp_path / "moves.jsonl"), documents_root=tmp_path)
    moved = mover.move(source, destination)
    assert moved.phase == "CONFLICT"
    assert source.exists() and destination.exists()


def test_failed_move_does_not_commit_proposed_path(tmp_path: Path):
    item = row()
    key = logical_version_key(item)
    result = StatusReconciliationService().reconcile(
        [item], {key: StatusObservation(SaleStatus.ENDED, raw_status="판매중지")}
    )
    committed = result.commit_actions({key: False})
    assert committed[0]["saved_relative_path"] == item["saved_relative_path"]
    assert committed[0]["sale_status"] == item["sale_status"]


def test_journal_rejects_middle_corruption_but_tolerates_torn_final(tmp_path: Path):
    path = tmp_path / "moves.jsonl"
    path.write_text('{"action_id":"a","phase":"PLANNED","source":"s","destination":"d","timestamp":"t","schema_version":2}\nnot-json\n', encoding="utf-8")
    try:
        RenameJournal(path).events()
    except ValueError:
        pass
    else:
        raise AssertionError("newline-terminated corruption must fail")
    path.write_text('{"action_id":"a","phase":"PLANNED","source":"s","destination":"d","timestamp":"t","schema_version":2}\n{"action_id":"b"', encoding="utf-8")
    journal = RenameJournal(path)
    assert len(journal.events()) == 1
    journal.append(RenameEvent("c", "PLANNED", "s2", "d2", "t2"))
    assert [event.action_id for event in journal.events()] == ["a", "c"]


def test_journal_repairs_clean_final_without_newline_before_append(tmp_path: Path):
    path = tmp_path / "moves.jsonl"
    path.write_text('{"action_id":"a","phase":"PLANNED","source":"s","destination":"d","timestamp":"t","schema_version":2}', encoding="utf-8")
    journal = RenameJournal(path)
    assert len(journal.events()) == 1
    journal.append(RenameEvent("b", "PLANNED", "s2", "d2", "t2"))
    assert [event.action_id for event in journal.events()] == ["a", "b"]


def test_move_does_not_adopt_unjournaled_existing_destination(tmp_path: Path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    destination.mkdir()
    mover = StatusFolderMover(RenameJournal(tmp_path / "moves.jsonl"), documents_root=tmp_path)
    result = mover.move(source, destination)
    assert result.phase == "CONFLICT"
    assert result.error == "source_missing_existing_destination"
