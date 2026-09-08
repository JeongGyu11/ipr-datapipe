"""PDF Load 단계의 입력, 출력, 상태 모델."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


LOAD_SCHEMA_VERSION = "pdf-load-v6"
LOADER_VERSION = "pdf-loader-v6"
PARSER_VERSION = "prosure-pdf2md-v6"


class LoadStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    OCR_REQUIRED = "OCR_REQUIRED"
    FAILED = "FAILED"


class RunStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class PageStatus(StrEnum):
    TEXT = "TEXT"
    OCR_REQUIRED = "OCR_REQUIRED"
    EMPTY = "EMPTY"


class TableQualityStatus(StrEnum):
    MEANINGFUL = "MEANINGFUL"
    FRAGMENT = "FRAGMENT"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class LoadTarget:
    input_index: int
    source_path: Path
    source_kind: str = "LOCAL_PATH"
    document_key: str | None = None
    product_version_key: str | None = None


@dataclass(frozen=True)
class ParsedTable:
    table_id: str
    page_no: int
    table_index: int
    bbox: list[float]
    row_count: int
    column_count: int
    markdown_path: str
    xlsx_path: str
    rendered_image_path: str = ""
    processed_markdown_path: str = ""
    contained_by: str | None = None
    included_in_page: bool = True
    reconstruction: dict[str, Any] | None = None
    quality_status: TableQualityStatus = TableQualityStatus.MEANINGFUL
    quality_reason: str = "STRUCTURED_TABLE"


@dataclass(frozen=True)
class ParsedPage:
    page_no: int
    width: float
    height: float
    text_raw: str
    text_content: str
    content_markdown: str
    meaningful_character_count: int
    word_count: int
    image_count: int
    largest_image_area_ratio: float
    page_status: PageStatus
    table_refs: list[str] = field(default_factory=list)
    image_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParsedImage:
    image_id: str
    first_page_no: int
    pixel_width: int
    pixel_height: int
    format: str
    image_path: str
    sha256: str
    extraction_mode: str
    occurrences: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PdfParseOutput:
    pages: list[ParsedPage]
    tables: list[ParsedTable]
    images: list[ParsedImage]
    raw_text: str
    content_markdown: str
    cropped_pdf_path: Path | None
    header_footer_analysis: dict[str, Any]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    text_source: str = "PDF_TEXT"
    rejected_table_count: int = 0
    table_reconstruction_enabled: bool = False

    @property
    def effective_text_length(self) -> int:
        return len("".join(self.content_markdown.split()))

    @property
    def ocr_required_pages(self) -> list[int]:
        return [page.page_no for page in self.pages if page.page_status is PageStatus.OCR_REQUIRED]

    @property
    def empty_pages(self) -> list[int]:
        return [page.page_no for page in self.pages if page.page_status is PageStatus.EMPTY]

    @property
    def page_status_counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in PageStatus}
        for page in self.pages:
            counts[page.page_status.value] += 1
        return counts

    @property
    def detected_table_count(self) -> int:
        return len(self.tables) + self.rejected_table_count

    @property
    def fragment_table_count(self) -> int:
        return sum(
            1
            for table in self.tables
            if table.quality_status is TableQualityStatus.FRAGMENT
        )

    @property
    def table_reconstruction_summary(self) -> dict[str, int]:
        statuses = [
            str(table.reconstruction.get("status"))
            for table in self.tables
            if table.reconstruction
        ]
        return {
            "eligible_count": sum(
                table.quality_status is TableQualityStatus.MEANINGFUL
                for table in self.tables
            ),
            "succeeded_count": statuses.count("SUCCEEDED"),
            "fallback_count": statuses.count("FALLBACK"),
            "passthrough_count": statuses.count("PASSTHROUGH_DISABLED"),
            "skipped_count": statuses.count("SKIPPED_NOT_MEANINGFUL"),
        }


@dataclass(frozen=True)
class PreparedLoadItem:
    target: LoadTarget
    item_dir: Path
    final_item_dir: Path
    copied_pdf_path: Path
    sha256: str
    size_bytes: int


@dataclass
class PdfLoadItemResult:
    input_index: int
    source_path: str
    status: LoadStatus
    item_dir: str | None = None
    sha256: str | None = None
    page_count: int = 0
    table_count: int = 0
    image_count: int = 0
    table_image_count: int = 0
    effective_text_length: int = 0
    ocr_required_pages: list[int] = field(default_factory=list)
    empty_pages: list[int] = field(default_factory=list)
    page_status_counts: dict[str, int] = field(default_factory=dict)
    error_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass(frozen=True)
class PdfLoadRequest:
    pdf_paths: tuple[Path, ...]


@dataclass
class PdfLoadResult:
    status: RunStatus
    items: list[PdfLoadItemResult]

    @property
    def exit_code(self) -> int:
        return 0 if self.status is RunStatus.SUCCEEDED else 1
