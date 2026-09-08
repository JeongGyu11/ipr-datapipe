"""보험사 기준정보의 단일 Python catalog.

보험사 코드는 문서 identity와 저장 경로에 포함되는 영구 식별자다.  따라서
수집 실행 설정(config.yaml)과 분리해 이 모듈에서 한 번만 정의한다.  향후
DB catalog로 이전할 때도 ``CompanyDefinition``의 필드가 그대로 이관될 수
있도록 업무 기준정보와 adapter 구현체 연결을 분리한다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


class InsuranceType(StrEnum):
    LIFE = "life"
    NON_LIFE = "non_life"


class CollectionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class CompanyDefinition:
    """보험사 업무 기준정보.

    ``code``는 변경하지 않는 영구 식별자이며 ``name``은 표시명,
    ``storage_name``은 파일 저장 폴더명으로 각각 독립적으로 관리한다.
    """

    code: str
    name: str
    storage_name: str
    insurance_type: InsuranceType
    collection_status: CollectionStatus
    entry_url: str
    disclosure_url: str = ""
    options: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

def _company(
    code: str,
    name: str,
    insurance_type: InsuranceType,
    entry_url: str,
    *,
    disclosure_url: str = "",
    options: Mapping[str, Any] | None = None,
    status: CollectionStatus = CollectionStatus.ACTIVE,
) -> CompanyDefinition:
    return CompanyDefinition(
        code=code,
        name=name,
        storage_name=name,
        insurance_type=insurance_type,
        collection_status=status,
        entry_url=entry_url,
        disclosure_url=disclosure_url,
        options=MappingProxyType(dict(options or {})),
    )


# 현재 config.yaml에 있던 30개 보험사 정의를 이곳으로 이전했다.
COMPANIES: tuple[CompanyDefinition, ...] = (
    # 손해보험
    _company("DB", "DB손해보험", InsuranceType.NON_LIFE, "https://www.idbins.com/FWMAIV1534.do"),
    _company("LOTTE", "롯데손해보험", InsuranceType.NON_LIFE, "https://www.lotteins.co.kr/web/C/D/H/cdh190.jsp"),
    _company("MERITZ", "메리츠화재", InsuranceType.NON_LIFE, "https://www.meritzfire.com/disclosure/product-announcement/product-list.do?vMode=PC"),
    _company(
        "KB", "KB손해보험", InsuranceType.NON_LIFE, "https://www.kbinsure.co.kr/CG802030001.ecs",
        options={"max_products": None},
    ),
    _company("SAMSUNG", "삼성화재", InsuranceType.NON_LIFE, "https://www.samsungfire.com/vh/page/VH.HPIF0103.do"),
    _company(
        "LINA_NON_LIFE", "라이나손해보험", InsuranceType.NON_LIFE,
        "https://www.chubb.com/kr-kr/disclosure/product-disclosure.html",
        disclosure_url="https://ec.aceinsurance.co.kr/jsp/acelimited/notice/productNoticeV2.jsp?status=Y",
    ),
    _company("HANA_NON_LIFE", "하나손해보험", InsuranceType.NON_LIFE, "https://m.hanainsure.co.kr/w/disclosure/product/saleProduct"),
    _company("HYUNDAI_MARINE", "현대해상", InsuranceType.NON_LIFE, "https://www.hi.co.kr/serviceAction.do?view=bin%2FPA%2F03%2FHHPA03020M"),
    _company("HEUNGKUK_FIRE", "흥국화재", InsuranceType.NON_LIFE, "https://www.heungkukfire.co.kr/FRW/announce/insGoodsGongsiSale.do"),
    _company(
        "AIG", "AIG손해보험", InsuranceType.NON_LIFE, "https://www.aig.co.kr/wm/content.html?contentId=DPWMS701",
        disclosure_url="https://www.aig.co.kr/wo/dpwot001.html?menuId=MS702",
        options={"legacy_ssl": True},
    ),
    _company("NH_FIRE", "NH농협손해보험", InsuranceType.NON_LIFE, "https://www.nhfire.co.kr/announce/productAnnounce/retrieveInsuranceProductsAnnounce.nhfire"),
    _company(
        "HANWHA_FIRE", "한화손해보험", InsuranceType.NON_LIFE,
        "https://www.hwgeneralins.com/notice/ir/product-main.do?mtoh=Y",
        status=CollectionStatus.ACCESS_RESTRICTED,
    ),
    # 생명보험
    _company(
        "KYOBO_LIFE", "교보생명", InsuranceType.LIFE, "https://www.kyobo.com/dgt/web/product-official/information",
        disclosure_url="https://www.kyobo.com/dgt/web/product-official/all-product/search",
        options={"max_products": None},
    ),
    _company("MIRAE_LIFE", "미래에셋생명", InsuranceType.LIFE, "https://life.miraeasset.com/micro/disclosure/product/PC-HO-080301-000000.do"),
    _company("DB_LIFE", "DB생명", InsuranceType.LIFE, "https://www.idblife.com/notice/product/sale", options={"legacy_ssl": True}),
    _company(
        "ABL_LIFE", "ABL생명", InsuranceType.LIFE, "https://abllife.co.kr/st/custDesk/cspCntr/fncLvngInfo/fncLvngInfo3?page=index",
        disclosure_url="https://abllife.co.kr/st/pban/prdtPban/whlPrdt/whlPrdt1/whlPrdt11?page=index",
    ),
    _company("IBK_LIFE", "IBK연금보험", InsuranceType.LIFE, "https://www.ibki.co.kr/process/HP_PBANO_PDT_SP_INDV"),
    _company("IM_LIFE", "iM라이프", InsuranceType.LIFE, "https://www.imlifeins.co.kr/BA/BA_A020.do"),
    _company("KB_LIFE", "KB라이프생명", InsuranceType.LIFE, "https://www.kblife.co.kr/customer-common/productList.do"),
    _company("KDB_LIFE", "KDB생명", InsuranceType.LIFE, "https://www.kdblife.com/ajax.do?pcmode=1&scrId=HDLMA002M02P"),
    _company("NH_LIFE", "NH농협생명", InsuranceType.LIFE, "https://www.nhlife.co.kr/ho/on/HOON0004M00.nhl"),
    _company(
        "TONGYANG_LIFE", "동양생명", InsuranceType.LIFE, "https://pbano.myangel.co.kr/",
        disclosure_url="https://pbano.myangel.co.kr/paging/WE_AC_WEPAAP020100L",
    ),
    _company("LINA_LIFE", "라이나생명", InsuranceType.LIFE, "https://www.lina.co.kr/disclosure/product-public-announcement/product-on-sales"),
    _company("METLIFE", "메트라이프생명", InsuranceType.LIFE, "https://brand.metlife.co.kr/pn/mcvrgProd/retrieveMcvrgProdMain.do"),
    _company("SAMSUNG_LIFE", "삼성생명", InsuranceType.LIFE, "https://www.samsunglife.com/individual/products/disclosure/sales/PDO-PRPRI010110M"),
    _company(
        "SHINHAN_LIFE", "신한라이프", InsuranceType.LIFE, "https://www.shinhanlife.co.kr/hp/cdhi0010.do",
        disclosure_url="https://www.shinhanlife.co.kr/hp/cdhi0030.do",
    ),
    _company(
        "FUBON_HYUNDAI_LIFE", "푸본현대생명", InsuranceType.LIFE, "https://www.fubonhyundai.com/",
        status=CollectionStatus.ACCESS_RESTRICTED,
    ),
    _company("HANA_LIFE", "하나생명", InsuranceType.LIFE, "https://www.hanalife.co.kr/anm/product/allProduct.do?status=on"),
    _company(
        "HANWHA_LIFE", "한화생명", InsuranceType.LIFE,
        "https://www.hanwhalife.com/redirect.asp?%2Fannounce%2Fgoods%2Fgoods%2Fgoodlist01.asp=",
        disclosure_url="https://www.hanwhalife.com/main/disclosure/goods/disclosurenotice/DF_GDDN000_P10000.do?MENU_ID1=DF_GDGL000&MENU_ID2=DF_GDGL000_P10000",
        options={"legacy_ssl": True},
    ),
    _company("HEUNGKUK_LIFE", "흥국생명", InsuranceType.LIFE, "https://www.heungkuklife.co.kr/front/public/saleProduct.do?searchFlgSale=Y"),
)

COMPANY_BY_CODE: dict[str, CompanyDefinition] = {company.code: company for company in COMPANIES}
_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def validate_company_catalog(
    companies: tuple[CompanyDefinition, ...] = COMPANIES,
    adapter_registry: Mapping[str, object] | None = None,
) -> None:
    """catalog 자체와 선택적인 adapter 연결 계약을 검증한다."""

    codes = [company.code for company in companies]
    if len(codes) != len(set(codes)):
        raise ValueError("보험사 코드가 중복되었습니다")
    names = [company.name for company in companies]
    if len(names) != len(set(names)):
        raise ValueError("보험사 이름이 중복되었습니다")
    for company in companies:
        if not _CODE_PATTERN.fullmatch(company.code):
            raise ValueError(f"보험사 코드 형식이 잘못되었습니다: {company.code}")
        if not company.name.strip() or not company.storage_name.strip():
            raise ValueError(f"보험사 이름/저장 이름이 비어 있습니다: {company.code}")
        if not company.entry_url.strip():
            raise ValueError(f"보험사 진입 URL이 비어 있습니다: {company.code}")
        if not isinstance(company.options, Mapping):
            raise ValueError(f"보험사 옵션은 mapping이어야 합니다: {company.code}")

    if adapter_registry is None:
        return
    catalog_codes = set(codes)
    registry_codes = {str(code).upper() for code in adapter_registry}
    missing = sorted(
        company.code
        for company in companies
        if company.collection_status is CollectionStatus.ACTIVE
        and company.code not in registry_codes
    )
    if missing:
        raise ValueError(f"ACTIVE 보험사에 Adapter가 없습니다: {', '.join(missing)}")
    extra = sorted(registry_codes - catalog_codes)
    if extra:
        raise ValueError(f"catalog에 없는 Adapter 코드가 있습니다: {', '.join(extra)}")
    mismatched = sorted(
        code
        for code, adapter in adapter_registry.items()
        if str(adapter.code).upper() != str(code).upper()
    )
    if mismatched:
        raise ValueError(f"Adapter 코드가 registry 키와 다릅니다: {', '.join(mismatched)}")


validate_company_catalog()


def get_company(code: str) -> CompanyDefinition:
    """코드로 보험사를 조회한다. 입력은 대소문자를 구분하지 않는다."""

    normalized = str(code).strip().upper()
    try:
        return COMPANY_BY_CODE[normalized]
    except KeyError as exc:
        raise ValueError(f"등록되지 않은 보험사 코드입니다: {code}") from exc


def validate_company_selection(
    codes: Iterable[str],
    adapter_registry: Mapping[str, object],
) -> tuple[str, ...]:
    """명시된 수집 대상을 검증하고 정규화된 보험사 코드를 반환한다."""

    validate_company_catalog(adapter_registry=adapter_registry)
    selected: list[str] = []
    for raw_code in codes:
        company = get_company(raw_code)
        if company.collection_status is CollectionStatus.ACCESS_RESTRICTED:
            raise ValueError(f"보험사 {company.code}는 현재 접근 제한 상태입니다")
        if company.collection_status is not CollectionStatus.ACTIVE:
            raise ValueError(
                f"보험사 {company.code}는 수집 비활성 상태입니다: "
                f"{company.collection_status.value}"
            )
        if company.code not in adapter_registry:
            raise ValueError(f"보험사 {company.code}에 Adapter가 없습니다")
        if company.code not in selected:
            selected.append(company.code)
    return tuple(selected)


__all__ = [
    "CollectionStatus",
    "CompanyDefinition",
    "COMPANIES",
    "COMPANY_BY_CODE",
    "InsuranceType",
    "get_company",
    "validate_company_catalog",
    "validate_company_selection",
]
