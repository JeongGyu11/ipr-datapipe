"""보험사별 Adapter 레지스트리."""

from __future__ import annotations

# --- 기존 5개사 (손해보험) -------------------------------------------------
from crawler.adapters.db_insurance import DBInsuranceAdapter
from crawler.adapters.kb_insurance import KBInsuranceAdapter
from crawler.adapters.lotte_insurance import LotteInsuranceAdapter
from crawler.adapters.meritz_insurance import MeritzInsuranceAdapter
from crawler.adapters.samsung_insurance import SamsungInsuranceAdapter

# --- 신규 생명보험사 -------------------------------------------------------
from crawler.adapters.abl_life import ABLLifeAdapter
from crawler.adapters.db_life import DBLifeAdapter
from crawler.adapters.hana_life import HanaLifeAdapter
from crawler.adapters.hanwha_life import HanwhaLifeAdapter
from crawler.adapters.heungkuk_life import HeungkukLifeAdapter
from crawler.adapters.ibk_life import IBKLifeAdapter
from crawler.adapters.im_life import IMLifeAdapter
from crawler.adapters.kb_life import KBLifeAdapter
from crawler.adapters.kdb_life import KDBLifeAdapter
from crawler.adapters.kyobo_life import KyoboLifeAdapter
from crawler.adapters.lina_life import LinaLifeAdapter
from crawler.adapters.metlife import MetLifeAdapter
from crawler.adapters.mirae_life import MiraeLifeAdapter
from crawler.adapters.nh_life import NHLifeAdapter
from crawler.adapters.samsung_life import SamsungLifeAdapter
from crawler.adapters.shinhan_life import ShinhanLifeAdapter
from crawler.adapters.tongyang_life import TongyangLifeAdapter

# --- 신규 손해보험사 -------------------------------------------------------
from crawler.adapters.aig import AIGAdapter
from crawler.adapters.hana_non_life import HanaNonLifeAdapter
from crawler.adapters.heungkuk_fire import HeungkukFireAdapter
from crawler.adapters.hyundai_marine import HyundaiMarineAdapter
from crawler.adapters.lina_non_life import LinaNonLifeAdapter
from crawler.adapters.nh_fire import NHFireAdapter

#: 보험사 코드 -> Adapter 클래스
#: ACTIVE catalog 항목은 반드시 같은 코드의 Adapter를 가져야 합니다.
ADAPTER_REGISTRY = {
    # 기존 5개사 (변경 금지)
    "DB": DBInsuranceAdapter,
    "LOTTE": LotteInsuranceAdapter,
    "MERITZ": MeritzInsuranceAdapter,
    "KB": KBInsuranceAdapter,
    "SAMSUNG": SamsungInsuranceAdapter,
    # 생명보험
    "KYOBO_LIFE": KyoboLifeAdapter,
    "MIRAE_LIFE": MiraeLifeAdapter,
    "DB_LIFE": DBLifeAdapter,
    "ABL_LIFE": ABLLifeAdapter,
    "KDB_LIFE": KDBLifeAdapter,
    "NH_LIFE": NHLifeAdapter,
    "TONGYANG_LIFE": TongyangLifeAdapter,
    "SHINHAN_LIFE": ShinhanLifeAdapter,
    "HEUNGKUK_LIFE": HeungkukLifeAdapter,
    "LINA_LIFE": LinaLifeAdapter,
    "SAMSUNG_LIFE": SamsungLifeAdapter,
    "HANWHA_LIFE": HanwhaLifeAdapter,
    "IBK_LIFE": IBKLifeAdapter,
    "IM_LIFE": IMLifeAdapter,
    "KB_LIFE": KBLifeAdapter,
    "METLIFE": MetLifeAdapter,
    "HANA_LIFE": HanaLifeAdapter,
    # 손해보험
    "LINA_NON_LIFE": LinaNonLifeAdapter,
    "HANA_NON_LIFE": HanaNonLifeAdapter,
    "HYUNDAI_MARINE": HyundaiMarineAdapter,
    "HEUNGKUK_FIRE": HeungkukFireAdapter,
    "NH_FIRE": NHFireAdapter,
    "AIG": AIGAdapter,
}

__all__ = [
    "ADAPTER_REGISTRY",
    "DBInsuranceAdapter",
    "LotteInsuranceAdapter",
    "MeritzInsuranceAdapter",
    "KBInsuranceAdapter",
    "SamsungInsuranceAdapter",
    "KyoboLifeAdapter",
    "MiraeLifeAdapter",
    "DBLifeAdapter",
    "IBKLifeAdapter",
    "IMLifeAdapter",
    "KBLifeAdapter",
    "MetLifeAdapter",
    "HanaLifeAdapter",
    "HanaNonLifeAdapter",
    "HyundaiMarineAdapter",
    "HeungkukFireAdapter",
    "ABLLifeAdapter",
    "KDBLifeAdapter",
    "NHLifeAdapter",
    "TongyangLifeAdapter",
    "ShinhanLifeAdapter",
    "HeungkukLifeAdapter",
    "LinaNonLifeAdapter",
    "NHFireAdapter",
    "LinaLifeAdapter",
    "SamsungLifeAdapter",
    "HanwhaLifeAdapter",
    "AIGAdapter",
]
