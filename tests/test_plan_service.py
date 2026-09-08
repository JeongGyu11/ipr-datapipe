"""장기 백필 plan JSONL/월별 인덱스/재개 테스트."""

import json
from datetime import date
from pathlib import Path

import pytest

import crawler.plan_service as plan_service_module
from crawler.config import load_config
from crawler.download_service import DownloadService
from crawler.manifest_service import ManifestService
from crawler.path_service import PathService
from crawler.plan_service import PlanItem, PlanService
from models.document import Document, DocumentType, DownloadStatus
from models.product_version import ProductVersion
from utils.crawler_logger import ErrorRecorder, setup_logging


ROOT = Path(__file__).resolve().parents[1]
PDF = (ROOT / "tests" / "fixtures" / "sample.pdf").read_bytes()


def make_version(start: date, name: str = "상품") -> ProductVersion:
    return ProductVersion(
        company_code="KB",
        company_name="KB손해보험",
        storage_name="KB손해보험",
        product_name_raw=name,
        product_category="건강",
        source_product_id="id-1",
        source_page_url="https://example.test/product",
        sale_status="판매중",
        sale_start_date=start,
        version_key=f"{start:%Y%m%d}_판매개시",
        documents=[Document(DocumentType.POLICY, "약관", "https://example.test/a.pdf", "a.pdf")],
    )


def make_plan_item(**kwargs) -> PlanItem:
    kwargs.setdefault("company_code", "KB")
    kwargs.setdefault("company_name", "KB손해보험")
    kwargs.setdefault("storage_name", "KB손해보험")
    return PlanItem(**kwargs)


def test_plan_is_durable_deduplicated_and_monthly_indexed(tmp_path):
    plan = PlanService(tmp_path / "kb_backfill.jsonl")
    version_2024 = make_version(date(2024, 1, 1))
    assert plan.add_version(version_2024, version_2024.documents[0]) is not None
    # 동일 상품/버전/문서는 한 번만 계획에 들어간다.
    assert plan.add_version(version_2024, version_2024.documents[0]) is None
    version_2025 = make_version(date(2025, 7, 1), "상품B")
    assert plan.add_version(version_2025, version_2025.documents[0]) is not None

    grouped = plan.create_monthly_index()
    assert set(grouped) == {"2024-01", "2025-07"}
    assert len(grouped["2024-01"]) == 1
    assert (tmp_path / "months.v3" / "2024-01.json").exists()
    assert (tmp_path / "months.v3" / "monthly_index.json").exists()

    reopened = PlanService(tmp_path / "kb_backfill.jsonl")
    assert len(reopened.items()) == 2


def test_read_only_scan_does_not_repair_missing_terminal_newline(tmp_path):
    path = tmp_path / "download_plan.v3.jsonl"
    item = PlanItem(
        company_code="KB",
        company_name="KB손해보험",
        storage_name="KB손해보험",
        target_date="2026-08-01",
        document_type="POLICY",
        document_url="https://example.test/policy.pdf",
    )
    original = json.dumps(item.to_row(), ensure_ascii=False).encode("utf-8")
    path.write_bytes(original)

    assert PlanService(path, repair=False).items()[0].company_code == "KB"
    assert path.read_bytes() == original

    assert PlanService(path).items()[0].company_code == "KB"
    assert path.read_bytes().endswith(b"\n")


def test_sale_end_status_change_does_not_create_second_plan_item(tmp_path):
    plan = PlanService(tmp_path / "99_운영" / "state" / "plan.jsonl")
    active = make_version(date(2024, 1, 1))
    assert plan.add_version(active, active.documents[0]) is not None

    ended = make_version(date(2024, 1, 1))
    ended.sale_status = "판매중지"
    ended.sale_end_date = date(2026, 8, 20)
    assert plan.add_version(ended, ended.documents[0]) is None
    assert len(plan.items()) == 1


def test_legacy_v1_plan_is_rejected(tmp_path):
    path = tmp_path / "plan.jsonl"
    legacy_version = make_version(date(2024, 1, 1))
    legacy = PlanItem.from_version(legacy_version, legacy_version.documents[0])
    legacy.schema_version = 1
    path.write_text(json.dumps(legacy.to_row(), ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError):
        PlanService(path)


def test_plan_date_range_and_post_download_hint_roundtrip(tmp_path):
    plan = PlanService(tmp_path / "documents" / "99_운영" / "state" / "plan.jsonl")
    version = make_version(date(2024, 2, 1))
    version.documents = [
        Document(DocumentType.POLICY, "POST 약관", original_filename="post.pdf", download_hint={"id": "42"})
    ]
    assert plan.add_versions([version], start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)) == 1
    item = plan.items()[0]
    assert item.to_version().sale_start_date == date(2024, 2, 1)
    assert item.to_document().download_hint == {"id": "42"}

    outside = make_version(date(2025, 1, 1), "제외")
    assert plan.add_versions([outside], start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)) == 0


def test_post_hint_plan_items_get_distinct_manifest_checkpoint_keys(tmp_path):
    setup_logging(None)
    config = load_config(ROOT / "config.yaml")
    paths = PathService(str(tmp_path), "documents", "2024-01")
    manifest = ManifestService(paths.output_root, "RUN")
    service = DownloadService(config, paths, manifest, ErrorRecorder(None), dry_run=True)
    version = make_version(date(2024, 1, 1))

    first = PlanItem.from_version(version, Document(
        DocumentType.POLICY, "약관", original_filename="same.pdf", download_hint={"id": "1"}
    ))
    second = PlanItem.from_version(version, Document(
        DocumentType.POLICY, "약관", original_filename="same.pdf", download_hint={"id": "2"}
    ))
    first_version = first.to_version()
    first_version.extra["_plan_checkpoint_key"] = first.plan_key
    second_version = second.to_version()
    second_version.extra["_plan_checkpoint_key"] = second.plan_key
    first_record = service._base_record(first_version, first.to_document())
    second_record = service._base_record(second_version, second.to_document())

    assert first_record.key() != second_record.key()


def test_plan_state_allows_failed_item_to_resume(tmp_path):
    plan = PlanService(tmp_path / "99_운영" / "state" / "plan.jsonl")
    item = make_plan_item(company_code="KB", product_name_raw="A", source_product_id="1", target_date="2024-01-01", document_type=DocumentType.POLICY, document_url="u")
    plan.add(item)
    plan.mark_result(item, DownloadStatus.DOWNLOAD_FAILED)
    assert len(list(plan.pending_items())) == 1
    saved = tmp_path / "saved.pdf"
    saved.write_bytes(b"ok")
    plan.mark_result(item, type("Result", (), {
        "download_status": DownloadStatus.SUCCESS,
        "saved_relative_path": "saved.pdf",
        "sha256": "",
        "error_message": "",
    })())
    assert list(plan.pending_items()) == []
    saved.unlink()
    assert len(list(plan.pending_items())) == 1


def test_pending_count_can_use_latest_state_without_file_stat(tmp_path, monkeypatch):
    plan = PlanService(tmp_path / "plan.jsonl")
    item = make_plan_item(
        company_code="KB",
        product_name_raw="상품",
        source_product_id="1",
        target_date="2024-01-01",
        document_type=DocumentType.POLICY,
        document_url="u",
    )
    plan.add(item)
    missing = tmp_path / "missing.pdf"
    plan.mark_result(
        item,
        type(
            "Result",
            (),
            {
                "download_status": DownloadStatus.SUCCESS,
                "saved_relative_path": "missing.pdf",
                "sha256": "",
                "error_message": "",
            },
        )(),
    )

    # 기본 경로는 유실 파일을 검출해 재처리 대상으로 남긴다.
    assert plan.pending_count() == 1
    # 종료 요약용 상태 전용 경로는 UNC 파일 stat 없이 완료 상태를 신뢰한다.
    original_strict_exists = plan_service_module.strict_exists

    def reject_missing_saved_path(path):
        if Path(path) == missing:
            raise AssertionError("status-only pending_count must not stat saved_relative_path")
        return original_strict_exists(path)

    monkeypatch.setattr(plan_service_module, "strict_exists", reject_missing_saved_path)
    assert plan.pending_count(verify_files=False) == 0


def test_canonical_plan_uses_named_download_state_file(tmp_path):
    plan = PlanService(tmp_path / "download_plan.v3.jsonl")
    assert plan.state_path == tmp_path / "download_state.v3.jsonl"


def test_plan_rejects_missing_storage_name(tmp_path):
    plan = PlanService(tmp_path / "download_plan.v3.jsonl")
    with pytest.raises(ValueError, match="storage_name"):
        plan.add(PlanItem(company_code="KB", product_name_raw="상품"))


def test_plan_torn_tail_is_truncated_before_append_and_reopen(tmp_path):
    path = tmp_path / "plan.jsonl"
    first = make_plan_item(company_code="KB", source_product_id="1", product_name_raw="첫째")
    path.write_text(json.dumps(first.to_row(), ensure_ascii=False) + "\n{" + '"company_code":"torn"', encoding="utf-8")

    service = PlanService(path)
    assert len(service.items()) == 1
    assert path.read_bytes().endswith(b"\n")

    second = make_plan_item(company_code="KB", source_product_id="2", product_name_raw="둘째")
    service.add(second)
    reopened = PlanService(path)
    assert [item.source_product_id for item in reopened.items()] == ["1", "2"]


def test_state_torn_tail_is_truncated_before_append_and_reopen(tmp_path):
    plan_path = tmp_path / "plan.jsonl"
    state_path = tmp_path / "state.jsonl"
    item = make_plan_item(company_code="KB", source_product_id="1", product_name_raw="상품")
    plan_path.write_text(json.dumps(item.to_row()) + "\n", encoding="utf-8")
    state_path.write_text(json.dumps({"schema_version": 3, "plan_key": item.plan_key, "dedupe_key": item.dedupe_key(), "download_status": "failed"}) + "\n{" + '"plan_key":"torn"', encoding="utf-8")

    service = PlanService(plan_path, state_path)
    assert service._states[item.plan_key]["download_status"] == "failed"
    assert state_path.read_bytes().endswith(b"\n")
    service.mark_result(item, DownloadStatus.DOWNLOAD_FAILED)

    reopened = PlanService(plan_path, state_path)
    assert set(reopened._states) == {item.plan_key}


def test_plan_valid_no_newline_tail_is_repaired_before_append_and_reopen(tmp_path):
    path = tmp_path / "plan.jsonl"
    first = make_plan_item(company_code="KB", source_product_id="1", product_name_raw="첫째")
    path.write_text(json.dumps(first.to_row()), encoding="utf-8")

    service = PlanService(path)
    assert path.read_bytes().endswith(b"\n")
    service.add(make_plan_item(company_code="KB", source_product_id="2", product_name_raw="둘째"))
    assert len(PlanService(path).items()) == 2


def test_state_valid_no_newline_tail_is_repaired_before_append_and_reopen(tmp_path):
    plan_path = tmp_path / "plan.jsonl"
    state_path = tmp_path / "state.jsonl"
    item = make_plan_item(company_code="KB", source_product_id="1", product_name_raw="상품")
    plan_path.write_text(json.dumps(item.to_row()) + "\n", encoding="utf-8")
    state_path.write_text(json.dumps({"schema_version": 3, "dedupe_key": item.dedupe_key(), "download_status": "failed"}), encoding="utf-8")

    service = PlanService(plan_path, state_path)
    assert state_path.read_bytes().endswith(b"\n")
    service.mark_result(item, DownloadStatus.DOWNLOAD_FAILED)
    assert set(PlanService(plan_path, state_path)._states) == {item.plan_key}


@pytest.mark.parametrize("bad_row", ['{"broken"', "[]"])
def test_plan_newline_terminated_or_middle_type_invalid_rows_are_fatal(tmp_path, bad_row):
    path = tmp_path / "plan.jsonl"
    valid = make_plan_item(company_code="KB", source_product_id="1", product_name_raw="상품")
    path.write_text(json.dumps(valid.to_row()) + "\n" + bad_row + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="손상"):
        PlanService(path)


def test_plan_middle_malformed_row_is_fatal(tmp_path):
    path = tmp_path / "plan.jsonl"
    first = make_plan_item(company_code="KB", source_product_id="1", product_name_raw="첫째")
    second = make_plan_item(company_code="KB", source_product_id="2", product_name_raw="둘째")
    path.write_text(
        json.dumps(first.to_row()) + "\n{" + '"broken"\n' + json.dumps(second.to_row()) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="손상"):
        PlanService(path)


def test_state_middle_and_newline_last_invalid_rows_are_fatal(tmp_path):
    plan_path = tmp_path / "plan.jsonl"
    state_path = tmp_path / "state.jsonl"
    item = make_plan_item(company_code="KB", source_product_id="1", product_name_raw="상품")
    plan_path.write_text(json.dumps(item.to_row()) + "\n", encoding="utf-8")
    valid = json.dumps({"plan_key": item.plan_key, "dedupe_key": item.dedupe_key(), "download_status": "failed"})
    state_path.write_text(valid + "\n[]\n" + json.dumps({"plan_key": "later"}) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="손상"):
        PlanService(plan_path, state_path)

    state_path.write_text(valid + "\n{" + '"broken"\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="손상"):
        PlanService(plan_path, state_path)


def test_state_key_mismatch_or_orphan_is_fatal(tmp_path):
    plan_path = tmp_path / "plan.jsonl"
    state_path = tmp_path / "state.jsonl"
    item = make_plan_item(company_code="KB", source_product_id="1", product_name_raw="상품")
    plan_path.write_text(json.dumps(item.to_row()) + "\n", encoding="utf-8")

    state_path.write_text(json.dumps({
        "plan_key": item.plan_key,
        "dedupe_key": "other",
        "download_status": "SUCCESS",
    }) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="손상"):
        PlanService(plan_path, state_path)

    state_path.write_text(json.dumps({"plan_key": "orphan", "download_status": "SUCCESS"}) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="손상"):
        PlanService(plan_path, state_path)


def test_existing_duplicate_plan_rows_are_yielded_once(tmp_path):
    path = tmp_path / "plan.jsonl"
    item = make_plan_item(company_code="KB", source_product_id="1", product_name_raw="상품")
    row = json.dumps(item.to_row(), ensure_ascii=False)
    path.write_text(row + "\n" + row + "\n", encoding="utf-8")

    service = PlanService(path)
    assert len(service.items()) == 1


def test_plan_append_does_not_reread_existing_jsonl(tmp_path, monkeypatch):
    path = tmp_path / "plan.jsonl"
    service = PlanService(path)
    calls = 0
    original = Path.read_bytes

    def counted_read_bytes(instance):
        nonlocal calls
        calls += 1
        return original(instance)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    service.add(make_plan_item(company_code="KB", source_product_id="1", product_name_raw="첫째"))
    service.add(make_plan_item(company_code="KB", source_product_id="2", product_name_raw="둘째"))
    assert calls == 0


class FakeAdapter:
    def __init__(self):
        self.calls = 0

    def fetch_document(self, document):
        from crawler.base_adapter import FetchResult

        self.calls += 1
        return FetchResult(ok=True, content=PDF, content_type="application/pdf", original_filename="a.pdf", http_status=200)

    def collect_documents(self, version):
        return version.documents


def test_download_service_process_plan_does_not_collect_again(tmp_path):
    setup_logging(None)
    config = load_config(ROOT / "config.yaml")
    paths = PathService(str(tmp_path), "documents", "2024-01")
    manifest = ManifestService(paths.output_root, "20260820_143000_ab12cd", paths.run_journal_path("20260820_143000_ab12cd", "KB"))
    manifest.load_previous()
    plan = PlanService(paths.output_root / "99_운영" / "state" / "plan.jsonl")
    service = DownloadService(config, paths, manifest, ErrorRecorder(None), plan_service=plan)
    version = make_version(date(2024, 1, 1))
    plan.add_version(version, version.documents[0])
    adapter = FakeAdapter()

    records = service.process_plan(adapter, plan)
    assert len(records) == 1
    assert records[0].download_status == DownloadStatus.SUCCESS
    assert adapter.calls == 1
    assert len(plan.state_path.read_text(encoding="utf-8").splitlines()) == 1
    # state 저널 덕분에 같은 plan을 재실행해도 다시 받지 않는다.
    records2 = service.process_plan(adapter, plan)
    assert records2 == []
    assert adapter.calls == 1


def test_range_collection_updates_canonical_plan_state(tmp_path):
    setup_logging(None)
    config = load_config(ROOT / "config.yaml")
    paths = PathService(str(tmp_path), "documents", "2024-01")
    manifest = ManifestService(paths.output_root, "20260820_143000_ab12cd", paths.run_journal_path("20260820_143000_ab12cd", "KB"))
    plan = PlanService(
        paths.state_dir("2024-01", "KB") / "download_plan.v3.jsonl",
        paths.state_dir("2024-01", "KB") / "download_state.v3.jsonl",
    )
    service = DownloadService(
        config, paths, manifest, ErrorRecorder(None), plan_service=plan
    )
    version = make_version(date(2024, 1, 1))

    records = service.process_version(FakeAdapter(), version)

    assert records[0].download_status == DownloadStatus.SUCCESS
    assert len(plan.items()) == 1
    assert list(plan.pending_items()) == []
    assert plan.state_path.name == "download_state.v3.jsonl"
    assert len(plan.state_path.read_text(encoding="utf-8").splitlines()) == 1
