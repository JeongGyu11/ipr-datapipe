from __future__ import annotations

import pytest

from crawler.adapters import ADAPTER_REGISTRY
from crawler.company_catalog import validate_company_catalog, validate_company_selection


def test_runtime_contract_accepts_current_catalog_and_registry() -> None:
    validate_company_catalog(adapter_registry=ADAPTER_REGISTRY)
    assert validate_company_selection([], ADAPTER_REGISTRY) == ()


def test_runtime_contract_rejects_unknown_selected_company() -> None:
    with pytest.raises(ValueError, match="등록되지 않은 보험사"):
        validate_company_selection(["NOT_A_COMPANY"], ADAPTER_REGISTRY)


def test_runtime_contract_rejects_access_restricted_company() -> None:
    with pytest.raises(ValueError, match="접근 제한"):
        validate_company_selection(["HANWHA_FIRE"], ADAPTER_REGISTRY)


def test_runtime_contract_rejects_adapter_code_mismatch() -> None:
    registry = dict(ADAPTER_REGISTRY)
    registry["KB"] = type("WrongKBAdapter", (), {"code": "DB"})
    with pytest.raises(ValueError, match="Adapter"):
        validate_company_catalog(adapter_registry=registry)


def test_runtime_contract_rejects_missing_active_adapter() -> None:
    registry = dict(ADAPTER_REGISTRY)
    registry.pop("DB")
    with pytest.raises(ValueError, match="ACTIVE 보험사"):
        validate_company_catalog(adapter_registry=registry)
