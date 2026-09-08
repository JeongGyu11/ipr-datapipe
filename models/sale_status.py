"""판매 상태의 공통 표현과 저장 경로용 접두사.

어댑터가 반환하는 ``판매중``, ``판매중지``, ``Y`` 등의 원문은 manifest에
그대로 보존하고, 파일 시스템 경로에서만 아래의 세 가지 상태로 정규화한다.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
import re
import unicodedata


class SaleStatus(StrEnum):
    """저장 경로에서 사용할 정규화된 판매 상태."""

    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    UNKNOWN = "UNKNOWN"


STATUS_PREFIX: dict[SaleStatus, str] = {
    SaleStatus.ACTIVE: "판매중__",
    SaleStatus.ENDED: "판매완료__",
    SaleStatus.UNKNOWN: "상태미상__",
}

# 상태값 비교 전에 공백·zero-width/BOM을 제거한다. 하이픈 등 일반 구분기호는
# 제거하지 않는다. 원문은 이 함수에 전달하기 전의 값으로 별도 보존해야 한다.
_COMPACT_RE = re.compile(r"[\s\u200b\ufeff]+")
_ACTIVE_VALUES = {
    "판매중", "판매", "진행중", "정상판매", "active", "open", "ongoing",
    "y", "yes", "true", "1",
}
_ENDED_VALUES = {
    "판매중지", "판매중단", "판매종료", "판매완료", "판매중지됨", "판매중단됨",
    "판매종료됨", "종료", "중지",
    "ended", "closed", "discontinued", "inactive", "n", "no", "false", "0",
}


def _status_key(value: object) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).strip().lower()
    return _COMPACT_RE.sub("", text)


def classify_sale_status(
    raw_status: object = "",
    *,
    explicit_status: SaleStatus | str | None = None,
    sale_end_date: date | None = None,
    as_of: date | None = None,
) -> SaleStatus:
    """원문 상태를 ``ACTIVE/ENDED/UNKNOWN``으로 변환한다.

    명시적인 원문/어댑터 상태를 날짜보다 우선한다. 종료일만 존재하는 경우
    임의의 날짜 필드가 판매종료일이라고 가정하지 않는다. 다만 확인되지 않은
    종료일이 미래라면 현재 시점에는 판매중일 수 있다는 정보만 사용한다.
    """

    if explicit_status is not None:
        try:
            return SaleStatus(str(explicit_status).upper())
        except ValueError:
            # 어댑터가 ``판매중`` 같은 원문을 explicit_status로 준 경우에도
            # 아래 원문 분류를 사용한다.
            raw_status = explicit_status

    key = _status_key(raw_status)
    if key in _ACTIVE_VALUES:
        return SaleStatus.ACTIVE
    if key in _ENDED_VALUES:
        return SaleStatus.ENDED

    # 종료일이 명시적 상태를 덮어쓰지는 않는다. 날짜가 미래인 경우에만
    # 현재 시점의 판매중 가능성을 안전하게 반영하고, 과거/당일은 UNKNOWN으로
    # 남겨 잘못된 판매완료 이동을 방지한다.
    if sale_end_date is not None:
        today = as_of or date.today()
        if sale_end_date > today:
            return SaleStatus.ACTIVE
    return SaleStatus.UNKNOWN


def status_prefix(status: SaleStatus | str) -> str:
    """정규화 상태에 대응하는 폴더 접두사를 반환한다."""

    try:
        normalized = status if isinstance(status, SaleStatus) else SaleStatus(str(status).upper())
    except ValueError:
        normalized = SaleStatus.UNKNOWN
    return STATUS_PREFIX[normalized]


__all__ = [
    "SaleStatus", "STATUS_PREFIX",
    "classify_sale_status", "status_prefix",
]
