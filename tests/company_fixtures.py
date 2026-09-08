"""공유하는 immutable catalog fixture helpers."""

from crawler.company_catalog import (
    CollectionStatus,
    CompanyDefinition,
    InsuranceType,
    get_company,
)


def company_definition(code: str, name: str | None = None, url: str = "https://example.test") -> CompanyDefinition:
    """실제 catalog 항목은 정본을 사용하고, fake 코드는 테스트 전용 정의를 만든다."""

    normalized = str(code).upper()
    try:
        return get_company(normalized)
    except ValueError:
        return CompanyDefinition(
            code=normalized,
            name=name or normalized,
            storage_name=name or normalized,
            insurance_type=InsuranceType.NON_LIFE,
            collection_status=CollectionStatus.ACTIVE,
            entry_url=url,
        )
