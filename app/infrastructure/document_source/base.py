"""Load 대상 선택기 계약."""

from __future__ import annotations

from typing import Protocol, Sequence

from app.domain.pdf_load import LoadTarget


class DocumentSelector(Protocol):
    def select(self, values: Sequence[str]) -> list[LoadTarget]: ...
