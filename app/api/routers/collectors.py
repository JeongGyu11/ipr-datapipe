"""등록된 보험사 수집기 조회 API."""

from __future__ import annotations

from fastapi import APIRouter

from crawler.adapters import ADAPTER_REGISTRY
from crawler.company_catalog import COMPANIES, CollectionStatus


router = APIRouter(prefix="/api/v1/collectors", tags=["collectors"])


@router.get("")
def list_collectors() -> dict[str, list[dict[str, object]]]:
    """보험사 catalog와 Adapter 메타데이터를 반환한다.

    ``config.yaml``은 실행 경로/다운로드 옵션만 제공하고, 보험사 목록의
    기준은 :mod:`crawler.company_catalog`으로 통일한다.
    """

    collectors: list[dict[str, object]] = []
    for company in COMPANIES:
        adapter_class = ADAPTER_REGISTRY.get(company.code.upper())
        status = company.collection_status
        status_value = status.value
        entry_url = company.entry_url
        disclosure_url = company.disclosure_url
        collectors.append(
            {
                "code": company.code,
                "name": company.name,
                "storage_name": company.storage_name,
                "url": entry_url,
                "disclosure_url": disclosure_url or None,
                "enabled": status is CollectionStatus.ACTIVE,
                "collection_status": status_value,
                "insurance_type": company.insurance_type,
                "adapter_available": adapter_class is not None,
                "collection_method": adapter_class.collection_method
                if adapter_class is not None
                else None,
            }
        )
    return {"collectors": collectors}
