"""KB 상세 체크포인트 저장 래퍼."""

from __future__ import annotations

from typing import Any

from crawler.detail_checkpoint_service import DetailCheckpointService


def product_key(product: dict[str, Any]) -> str:
    """KB 상품 상세 요청을 유일하게 식별하는 키."""
    aliases = {
        "bojong_no": ("bojong_no", "bojongNo"),
        "gubun": ("gubun",),
        "bojong_seq": ("bojong_seq", "bojongSeq"),
    }
    return "|".join(
        next((str(product[name]).strip() for name in names if name in product), "")
        for field in ("bojong_no", "gubun", "bojong_seq")
        for names in (aliases[field],)
    )


class KBCheckpointService(DetailCheckpointService):
    """KB 상세 결과를 v2 checkpoint 파일로 저장하는 래퍼."""

    def __init__(self, root: str, scope: str = "default", **kwargs: Any):
        kwargs.setdefault("filename", "kb_product_details.v2.jsonl")
        kwargs.setdefault("key_fn", product_key)
        super().__init__(root, scope=scope, **kwargs)


__all__ = ["KBCheckpointService", "product_key"]
