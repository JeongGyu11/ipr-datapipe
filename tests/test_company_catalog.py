from __future__ import annotations

import pytest

from crawler.adapters import ADAPTER_REGISTRY
from crawler.company_catalog import (
    COMPANIES,
    COMPANY_BY_CODE,
    CollectionStatus,
    get_company,
    validate_company_catalog,
)
from crawler.config import load_config


def test_catalog_has_unique_codes_and_expected_restricted_companies() -> None:
    assert len(COMPANIES) == 30
    assert len(COMPANY_BY_CODE) == 30
    assert {
        company.code
        for company in COMPANIES
        if company.collection_status is CollectionStatus.ACCESS_RESTRICTED
    } == {"FUBON_HYUNDAI_LIFE", "HANWHA_FIRE"}


def test_catalog_adapter_contract_matches_current_registry() -> None:
    validate_company_catalog(adapter_registry=ADAPTER_REGISTRY)
    assert set(ADAPTER_REGISTRY) <= set(COMPANY_BY_CODE)


def test_lookup_is_case_insensitive_and_rejects_unknown_code() -> None:
    assert get_company(" kb ").code == "KB"
    with pytest.raises(ValueError, match="등록되지 않은 보험사"):
        get_company("NOT_A_COMPANY")


def test_load_config_uses_catalog_as_company_source() -> None:
    config = load_config("config.yaml")
    assert not hasattr(config, "companies")
    assert not hasattr(config, "raw")
    kb = get_company("kb")
    assert kb.storage_name == "KB손해보험"
    assert kb.collection_status is CollectionStatus.ACTIVE
    assert get_company("FUBON_HYUNDAI_LIFE").collection_status is CollectionStatus.ACCESS_RESTRICTED
