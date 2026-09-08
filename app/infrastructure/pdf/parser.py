"""Contracts for PDF loading infrastructure."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.domain.pdf_load import PdfParseOutput


class PdfParser(Protocol):
    """Parser contract shared by the load application and implementations."""

    parser_version: str

    def parse(self, source_pdf: Path, item_dir: Path) -> PdfParseOutput:
        """Parse ``source_pdf`` and persist intermediate artifacts in ``item_dir``."""


__all__ = ["PdfParser"]
