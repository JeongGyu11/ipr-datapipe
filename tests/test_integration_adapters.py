"""보험사별 통합 테스트 (실제 사이트 호출).

기본적으로 건너뜁니다. 실행하려면:
    pytest -m network --run-network
    pytest -m network --run-network -k samsung

검증 항목(요구사항 §19 통합 테스트)
    1. 상품명 수집  2. 날짜 정보 수집  3~5. 약관/상품요약서/사업방법서 링크 수집
    6. 파일 다운로드  7. 저장 경로 생성  8. manifest 기록
    9. 다운로드 파일 정상 열림  10. 재실행 시 중복 다운로드 방지

실제 문서가 없는 경우 실패로 처리하지 않고 NO_DOCUMENT_LINK 가 기록되는지 확인합니다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from crawler.adapters import ADAPTER_REGISTRY
from crawler.config import load_config
from crawler.company_catalog import get_company
from crawler.download_service import DownloadService
from crawler.manifest_service import ManifestService
from crawler.path_service import PathService
from crawler.validators import DocumentClassifier
from models.document import DocumentType, DownloadStatus
from utils.crawler_logger import ErrorRecorder, setup_logging

ROOT = Path(__file__).resolve().parents[1]
MONTH_START, MONTH_END = date(2026, 7, 1), date(2026, 7, 31)

#: 통합 테스트에서 조회할 상품 수 상한 (사이트 부하 최소화)
PROBE_LIMITS = {"KB": 30, "KYOBO_LIFE": 25}


def _adapter(code: str, config):
    company = get_company(code)
    runtime_options = {
        **company.options,
        **({"max_products": PROBE_LIMITS[code]} if code in PROBE_LIMITS else {}),
    }
    classifier = DocumentClassifier(config.document_types, config.document_exclude_keywords)
    return ADAPTER_REGISTRY[code](company, config, classifier, runtime_options=runtime_options)


def test_adapter_factory_keeps_catalog_immutable_and_uses_runtime_options(app_config):
    before = {code: dict(get_company(code).options) for code in PROBE_LIMITS}

    for code, limit in PROBE_LIMITS.items():
        adapter = _adapter(code, app_config)
        company = get_company(code)
        assert adapter.code == company.code == ADAPTER_REGISTRY[code].code
        assert adapter.runtime_options["max_products"] == limit
        assert dict(company.options) == before[code]

    assert {code: dict(get_company(code).options) for code in PROBE_LIMITS} == before


@pytest.fixture(scope="module")
def app_config():
    setup_logging(None)
    return load_config(ROOT / "config.yaml")


@pytest.mark.parametrize(
    "code",
    ["DB", "LOTTE", "MERITZ", "KB", "SAMSUNG", "KYOBO_LIFE", "MIRAE_LIFE", "DB_LIFE"],
)
@pytest.mark.network
def test_adapter_end_to_end(code, app_config, tmp_path):
    adapter = _adapter(code, app_config)
    with adapter:
        versions = adapter.collect_product_versions(MONTH_START, MONTH_END)

        # 1. 상품명 수집 / 2. 날짜 정보 수집
        assert isinstance(versions, list)
        if not versions:
            pytest.skip(f"{code}: 2026-07 대상 상품 버전이 없어 다운로드 검증을 건너뜁니다.")
        for version in versions[:5]:
            assert version.product_name_raw, "상품명이 비어 있습니다"
            assert version.company_code == code
            assert version.date_basis in ("sale_start_date", "revision_date", "disclosure_date", "NONE")

        dated = [v for v in versions if v.sale_start_date is not None]
        assert dated, "판매개시일을 가진 버전이 하나도 없습니다"

        # 3~5. 문서유형별 링크 수집
        found_types = {
            d.document_type
            for v in versions
            for d in adapter.collect_documents(v)
            if d.has_link
        }
        assert found_types & {DocumentType.POLICY, DocumentType.SUMMARY, DocumentType.METHOD}, (
            f"{code}: 약관/상품요약서/사업방법서 링크를 하나도 찾지 못했습니다"
        )

        # 6~9. 실제 1건만 다운로드하여 검증
        paths = PathService(str(tmp_path), "insurance_product_documents", "2026-07",
                            app_config.max_path_length)
        manifest = ManifestService(output_root=paths.output_root, run_id="ITEST")
        manifest.load_previous()
        service = DownloadService(app_config, paths, manifest, ErrorRecorder(None))

        target = next((v for v in versions if any(d.has_link for d in v.documents)), None)
        if target is None:
            # 문서가 전혀 없어도 실패시키지 않고 상태만 확인한다.
            records = service.process_version(adapter, versions[0])
            assert records[0].download_status == DownloadStatus.NO_DOCUMENT_LINK
            return

        target.documents = target.documents[:1]
        records = service.process_version(adapter, target)
        record = records[0]
        assert record.download_status in (
            DownloadStatus.SUCCESS,
            DownloadStatus.DUPLICATE_SKIPPED,
            DownloadStatus.NO_DOCUMENT_LINK,
        ), f"{code}: {record.download_status} / {record.error_message}"

        if record.download_status == DownloadStatus.SUCCESS:
            saved = paths.resolve_relative_path(record.saved_relative_path)
            assert saved.exists() and saved.stat().st_size > 0      # 7, 9
            assert saved.read_bytes()[:5] in (b"%PDF-", b"PK\x03\x04"[:5]) or saved.suffix != ".pdf"
            assert record.sha256 and record.file_size               # 8

            # 10. 재실행 시 중복 다운로드 방지
            manifest2 = ManifestService(output_root=paths.output_root, run_id="ITEST2")
            manifest2.load_previous()
            service2 = DownloadService(app_config, paths, manifest2, ErrorRecorder(None))
            again = service2.process_version(adapter, target)
            assert again[0].download_status == DownloadStatus.DUPLICATE_SKIPPED
