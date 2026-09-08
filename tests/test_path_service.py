"""경로 생성 / UNC 경로 / 덮어쓰기 방지 테스트."""

from datetime import date
from pathlib import Path

import pytest

from crawler.path_service import NetworkPathError, PathService
from models.document import DocumentType
from models.product_version import ProductVersion

UNC_BASE = r"\\Fileserver\data\FAS\7.제안공유\04. 진행중\349.밀리만\상품리서치 Ai Agent\IPR"


def make_version(
    name="참좋은운전자상해보험",
    start=date(2026, 7, 15),
    end=None,
    company="DB손해보험",
    category="운전자보험",
    status="판매중",
):
    return ProductVersion(
        company_code="DB",
        company_name=company,
        storage_name=company,
        product_name_raw=name,
        product_category=category,
        source_page_url="https://www.idbins.com/FWMAIV1534.do",
        sale_status=status,
        sale_start_date=start,
        sale_end_date=end,
        version_key=f"{start:%Y%m%d}_판매개시" if start else "",
    )


def service(base=UNC_BASE, month="2026-07", max_len=240):
    return PathService(base_path=base, root_folder="상품공시실문서",
                       target_month=month, max_path_length=max_len)


# 5. UNC 네트워크 경로 생성 ----------------------------------------------------
def test_network_output_root():
    svc = service()
    expected = UNC_BASE + r"\상품공시실문서"
    assert str(svc.output_root) == expected


def test_folder_structure_matches_spec():
    svc = service()
    version = make_version()
    path, _ = svc.resolve_target_path(version, DocumentType.POLICY, ".pdf", "원본약관.pdf")
    assert str(path.parent).endswith(
        r"상품공시실문서\01_문서\DB손해보험\2026\07\판매중__20260715_참좋은운전자상해보험"
    )
    assert path.name == "약관.pdf"


def test_metadata_paths_are_separated_by_month_company_and_run():
    svc = service()
    assert not hasattr(svc, "collection_root")
    assert not hasattr(svc, "manifest_json_path")
    assert not hasattr(svc, "manifest_csv_path")
    assert str(svc.state_dir()).endswith(r"상품공시실문서\99_운영\state\2026-07")
    assert str(svc.state_dir("20240101_20260820", "db")).endswith(
        r"상품공시실문서\99_운영\state\20240101_20260820\DB"
    )
    assert str(svc.run_dir("20260820_143000_ab12cd")).endswith(
        r"상품공시실문서\99_운영\runs\2026\08\20\20260820_143000_ab12cd"
    )
    with pytest.raises(ValueError):
        svc.run_dir("RUN_123")
    assert str(svc.lock_path("db")).endswith(r"상품공시실문서\99_운영\locks\DB.lock")
    assert str(svc.download_staging_dir("20260820_143000_ab12cd", "db")).endswith(
        r"staging\20260820_143000_ab12cd\DB"
    )

    assert not hasattr(svc, "manifest_lock_path")
    assert str(svc.db_outbox_path("db")).endswith(r"db_outbox\DB.jsonl")


def test_db_outbox_uses_persistent_local_state_and_output_hash_isolation(monkeypatch, tmp_path):
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    first = service(base=r"\\Fileserver\data\first")
    second = service(base=r"\\Fileserver\data\second")

    first_path = first.db_outbox_path("db")
    second_path = second.db_outbox_path("db")
    assert first_path == first.local_state_root / "db_outbox" / "DB.jsonl"
    assert first_path.parent != second_path.parent
    assert first.local_state_root.parts[-3] == "insurance-document-crawler"
    assert first_path.parts[-3:] == ("state", "db_outbox", "DB.jsonl")
    # LOCALAPPDATA 자체가 pytest의 시스템 임시 경로 아래로 monkeypatch될
    # 수 있다. 중요한 계약은 별도 ``Temp`` 하위를 추가하지 않고 지정된
    # LOCALAPPDATA 바로 아래의 영속 state를 사용한다는 점이다.
    assert first.local_state_root.is_relative_to(local_app_data)
    assert not first.local_state_root.is_relative_to(local_app_data / "Temp")


def test_db_outbox_falls_back_to_repository_local_state(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    svc = service()
    expected_root = Path(__file__).resolve().parents[1] / ".local_state"
    assert svc.local_state_root == expected_root / "insurance-document-crawler" / svc.local_state_root.parts[-2] / "state"
    assert expected_root in svc.db_outbox_path("db").parents


def test_metadata_paths_use_period_scope_key():
    svc = PathService(
        base_path=UNC_BASE,
        root_folder="상품공시실문서",
        target_month="2024-01-01_2026-08-20",
        scope_key="20240101_20260820",
    )
    with pytest.raises(ValueError):
        svc.run_journal_path("RUN_123", "db")


def test_filename_rule():
    svc = service()
    version = make_version()
    name = svc.build_filename(version, DocumentType.POLICY, ".pdf", "원본약관.pdf")
    assert name == "약관.pdf"

    name = svc.build_filename(version, DocumentType.SUMMARY, ".pdf", "원본요약.PDF")
    assert name == "상품요약서.pdf"

    name = svc.build_filename(version, DocumentType.METHOD, ".pdf", "원본방법서.pdf")
    assert name == "사업방법서.pdf"


def test_filename_rule_for_stopped_sale():
    svc = service()
    version = make_version(end=date(2026, 7, 31), status="판매중지")
    name = svc.build_filename(version, DocumentType.POLICY, ".pdf", "원본약관.pdf")
    assert name == "약관.pdf"


@pytest.mark.parametrize(
    "status,end,prefix",
    [
        ("판매중", None, "판매중__"),
        ("판매중지", date(2026, 7, 31), "판매완료__"),
        ("판매완료", date(2026, 7, 31), "판매완료__"),
        ("", None, "상태미상__"),
    ],
)
def test_sale_status_prefixes(status, end, prefix):
    svc = service()
    version = make_version(end=end, status=status)
    path, _ = svc.resolve_target_path(version, DocumentType.POLICY, ".pdf")
    assert prefix in path.parent.name


def test_future_end_date_does_not_override_unknown_status():
    svc = service()
    version = make_version(end=date(2099, 1, 1), status="")
    path, _ = svc.resolve_target_path(version, DocumentType.POLICY, ".pdf")
    assert path.parent.name.startswith("상태미상__") is False
    # 미래 종료일은 현재 판매중일 가능성이 있으므로 ACTIVE로 분류한다.
    assert path.parent.name.startswith("판매중__")


def test_arbitrary_past_end_date_does_not_infer_ended():
    svc = service()
    version = make_version(end=date(2020, 1, 1), status="확인필요")
    path, _ = svc.resolve_target_path(version, DocumentType.POLICY, ".pdf")
    assert path.parent.name.startswith("상태미상__")


def test_unknown_version_folder():
    svc = service()
    version = make_version(start=None)
    version.version_key = ""
    assert version.resolved_version_key() == "UNKNOWN_VERSION"
    name = svc.build_filename(version, DocumentType.POLICY, ".pdf", "원본약관.pdf")
    assert name == "약관.pdf"
    path, _ = svc.resolve_target_path(version, DocumentType.POLICY, ".pdf")
    assert str(path.parent).endswith(
        r"상품공시실문서\01_문서\DB손해보험\날짜미상\판매중__날짜미상_참좋은운전자상해보험"
    )


def test_empty_product_category_falls_back_to_product_name():
    svc = service()
    version = make_version(category="")
    name = svc.build_filename(version, DocumentType.POLICY, ".pdf")
    assert name == "약관.pdf"


def test_missing_original_filename_uses_placeholder():
    svc = service()
    version = make_version()
    name = svc.build_filename(version, DocumentType.POLICY, ".pdf")
    assert name == "약관.pdf"


def test_filename_with_invalid_chars_in_product_name():
    svc = service()
    version = make_version(name='무배당 A/B:C*보험 <2607>')
    name = svc.resolve_target_path(version, DocumentType.POLICY, ".pdf")[0].parent.name
    for ch in '\\/:*?"<>|':
        assert ch not in name


def test_product_folder_has_no_whitespace_and_preserves_status_separator():
    svc = service()
    version = make_version(name="A _123123 상품")
    name = svc.resolve_target_path(version, DocumentType.POLICY, ".PDF ")[0].parent.name
    assert name == "판매중__20260715_A_123123_상품"
    assert not any(ch.isspace() for ch in name)
    assert name.startswith("판매중__")


def test_long_path_is_truncated_under_limit(tmp_path):
    svc = service(base=str(tmp_path), max_len=200)
    version = make_version(name="무배당 " + "아주긴상품명" * 40)
    path, filename = svc.resolve_target_path(version, DocumentType.POLICY, ".pdf")
    assert len(str(path)) <= 200
    assert filename.endswith(".pdf")
    assert "~" not in path.parent.name


def test_long_path_original_name_preserved_on_version():
    """경로는 축약해도 원본 상품명은 모델에 그대로 남는다(메타데이터 보존)."""
    original = "무배당 " + "아주긴상품명" * 40
    version = make_version(name=original)
    assert version.product_name_raw == original


# 9. 기존 파일 덮어쓰기 방지 ---------------------------------------------------
def test_next_available_path_adds_2_3(tmp_path):
    svc = service(base=str(tmp_path))
    target = tmp_path / "a.pdf"
    target.write_bytes(b"1")
    second = svc.next_available_path(target)
    assert second.name == "a_2.pdf"

    second.write_bytes(b"2")
    third = svc.next_available_path(target)
    assert third.name == "a_3.pdf"

    # 기존 파일은 그대로 남아 있어야 한다.
    assert target.read_bytes() == b"1"
    assert second.read_bytes() == b"2"


def test_next_available_path_returns_same_when_free(tmp_path):
    svc = service(base=str(tmp_path))
    target = tmp_path / "free.pdf"
    assert svc.next_available_path(target) == target


# 파일 서버 접근 검증 ----------------------------------------------------------
def test_verify_base_path_success(tmp_path):
    svc = service(base=str(tmp_path))
    assert svc.verify_base_path() == tmp_path
    # 테스트 파일이 남아 있지 않아야 한다.
    assert list(tmp_path.glob(".write_test_*")) == []


def test_verify_base_path_missing_raises():
    svc = service(base=r"\\NoSuchServer\NoSuchShare\nope")
    with pytest.raises(NetworkPathError) as exc:
        svc.verify_base_path()
    message = exc.value.format_message()
    assert "[ERROR] 파일 서버에 접근할 수 없습니다." in message
    assert "경로:" in message and "원인:" in message


def test_verify_base_path_empty_config():
    svc = service(base="")
    with pytest.raises(NetworkPathError):
        svc.verify_base_path()


def test_verify_base_path_rejects_file(tmp_path):
    file_path = tmp_path / "not_a_dir.txt"
    file_path.write_text("x", encoding="utf-8")
    svc = service(base=str(file_path))
    with pytest.raises(NetworkPathError):
        svc.verify_base_path()
