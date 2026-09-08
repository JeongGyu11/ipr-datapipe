"""공통 상세 체크포인트의 재개·손상 복구 계약 테스트."""

import json
from datetime import date
from pathlib import Path

import pytest

from crawler.detail_checkpoint_service import DetailCheckpointService
from models.document import Document
from models.product_version import ProductVersion


def _version() -> ProductVersion:
    return ProductVersion(
        company_code="X", company_name="테스트", storage_name="테스트", product_name_raw="상품",
        source_page_url="https://example.test", sale_start_date=date(2024, 1, 1),
        extra={"token": {"value": "abc"}},
        documents=[Document("POLICY", "약관", "https://example.test/a", "약관.pdf", {"x": 1})],
    )


def test_roundtrip_empty_success_and_latest_failure_state(tmp_path):
    product = {"id": "1", "name": "상품"}
    service = DetailCheckpointService(tmp_path, scope="scope", key_fn=lambda value: value["id"])
    service.record_success(product, [])
    assert service.reusable(product).versions == []
    service.record_failure(product, "503")
    assert service.reusable(product) is None
    service.record_success(product, [_version()])
    resumed = DetailCheckpointService(tmp_path, scope="scope", key_fn=lambda value: value["id"])
    checkpoint = resumed.reusable(product)
    assert checkpoint is not None
    assert checkpoint.versions[0].documents[0].download_hint == {"x": 1}
    assert checkpoint.versions[0].extra == {"token": {"value": "abc"}}


def test_explicit_path_scope_schema_and_torn_tail(tmp_path):
    path = tmp_path / "detail.jsonl"
    service = DetailCheckpointService(path=path, scope="one", key_fn=lambda value: value["id"], schema_version=2)
    service.record_success({"id": "1"}, [])
    path.write_text(path.read_text(encoding="utf-8") + '{"key":"torn"', encoding="utf-8")
    assert DetailCheckpointService(path=path, scope="one", key_fn=lambda value: value["id"], schema_version=2).completed_count() == 1
    assert DetailCheckpointService(path=path, scope="two", key_fn=lambda value: value["id"], schema_version=2).completed_count() == 0


def test_malformed_middle_row_is_fatal(tmp_path):
    path = tmp_path / "detail.jsonl"
    service = DetailCheckpointService(path=path, key_fn=lambda value: value["id"])
    service.record_success({"id": "1"}, [])
    path.write_text(path.read_text(encoding="utf-8") + "broken\n" + json.dumps({"key": "2", "product": {}, "versions": [], "status": "completed"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="중간 행"):
        DetailCheckpointService(path=path, key_fn=lambda value: value["id"])


def test_torn_tail_is_truncated_before_next_append(tmp_path):
    path = tmp_path / "detail.jsonl"
    service = DetailCheckpointService(path=path, key_fn=lambda value: value["id"])
    service.record_success({"id": "1"}, [])
    path.write_bytes(path.read_bytes() + b'{"key":"torn"')
    resumed = DetailCheckpointService(path=path, key_fn=lambda value: value["id"])
    resumed.record_success({"id": "2"}, [])
    reopened = DetailCheckpointService(path=path, key_fn=lambda value: value["id"])
    assert reopened.completed_count() == 2


def test_valid_no_newline_tail_is_repaired_before_next_append(tmp_path):
    path = tmp_path / "detail.jsonl"
    service = DetailCheckpointService(path=path, key_fn=lambda value: value["id"])
    service.record_success({"id": "1"}, [])
    path.write_bytes(path.read_bytes().rstrip(b"\r\n"))

    resumed = DetailCheckpointService(path=path, key_fn=lambda value: value["id"])
    assert path.read_bytes().endswith(b"\n")
    resumed.record_success({"id": "2"}, [])
    assert DetailCheckpointService(path=path, key_fn=lambda value: value["id"]).completed_count() == 2


def test_newline_terminated_malformed_last_row_is_fatal(tmp_path):
    path = tmp_path / "detail.jsonl"
    service = DetailCheckpointService(path=path, key_fn=lambda value: value["id"])
    service.record_success({"id": "1"}, [])
    path.write_bytes(path.read_bytes() + b"broken\n")
    with pytest.raises(RuntimeError):
        DetailCheckpointService(path=path, key_fn=lambda value: value["id"])


@pytest.mark.parametrize("bad_key", [None, 123, "   "])
def test_invalid_checkpoint_key_is_fatal(tmp_path, bad_key):
    path = tmp_path / "detail.jsonl"
    path.write_text(json.dumps({
        "key": bad_key,
        "scope": "default",
        "schema_version": 2,
        "status": "completed",
        "product": {},
        "versions": [],
    }) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="손상"):
        DetailCheckpointService(path=path)


@pytest.mark.parametrize("field, value", [("product", []), ("versions", {})])
def test_checkpoint_product_and_versions_types_are_fatal(tmp_path, field, value):
    path = tmp_path / "detail.jsonl"
    row = {
        "key": "1",
        "scope": "default",
        "schema_version": 2,
        "status": "completed",
        "product": {},
        "versions": [],
    }
    row[field] = value
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="손상"):
        DetailCheckpointService(path=path)


def test_crlf_terminal_repair_preserves_crlf(tmp_path):
    path = tmp_path / "detail.jsonl"
    service = DetailCheckpointService(path=path, key_fn=lambda value: value["id"])
    service.record_success({"id": "1"}, [])
    service.record_success({"id": "2"}, [])
    # 첫 행의 CRLF는 남겨 기존 파일 스타일을 판별할 근거를 제공하고,
    # 마지막 행의 종료 개행만 제거해 강제 종료 직전 상태를 재현한다.
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n").rstrip(b"\r\n"))

    DetailCheckpointService(path=path, key_fn=lambda value: value["id"])
    assert path.read_bytes().endswith(b"\r\n")


def test_checkpoint_append_does_not_reread_existing_jsonl(tmp_path, monkeypatch):
    path = tmp_path / "detail.jsonl"
    service = DetailCheckpointService(path=path, key_fn=lambda value: value["id"])
    calls = 0
    original = Path.read_bytes

    def counted_read_bytes(target):
        nonlocal calls
        if target == path:
            calls += 1
        return original(target)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    service.record_success({"id": "1"}, [])
    service.record_success({"id": "2"}, [])
    assert calls == 0


def test_legacy_row_is_rejected_without_fallback(tmp_path):
    path = tmp_path / "legacy.jsonl"
    path.write_text(
        json.dumps({
            "checkpoint_version": 1,
            "key": "legacy-1",
            "product": {"id": "legacy-1"},
            "status": "completed",
            "versions": [],
        }) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError):
        DetailCheckpointService(path=path, scope="scope")
