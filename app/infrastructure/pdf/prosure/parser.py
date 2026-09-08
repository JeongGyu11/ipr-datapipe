"""Standalone PDF parser adapted from the ProSure preprocessing loader.

The parser is intentionally an infrastructure component: it only receives a
source :class:`~pathlib.Path` and an output directory, and returns a
serialisable result.  No FastAPI, settings, application logger, or database
objects are imported here.
"""

from __future__ import annotations

import re
import uuid
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Iterable

from app.domain.llm import (
    ReconstructionStatus,
    TableReconstructor,
    select_representation_mode,
)

from .header_footer import analyze_header_footer
from .images import TableRegionRenderer, extract_embedded_images
from app.domain.pdf_load import (
    PARSER_VERSION,
    PageStatus,
    ParsedPage,
    ParsedTable,
    PdfParseOutput,
    TableQualityStatus,
)
from .table_quality import (
    TableAssessment,
    assess_table,
    bbox_contains,
    overlap_ratio,
    rejection_warning,
    table_fingerprint,
    table_text_fingerprint,
)

MEANINGFUL_CHARACTER_PATTERN = re.compile(r"[가-힣A-Za-z0-9]")
OCR_MINIMUM_CHARACTERS = 10
OCR_IMAGE_AREA_RATIO = 0.50

SECTION_LINE_PATTERN = re.compile(
    r"special\s+extensions\s+and\s+provisions\s+applicable\s+to\s+section"
    r"|section\s*[\u2160-\u2188ivxlcdm0-9]+"
    r"|sec(?:\.|\s*)[\u2160-\u2188ivxlcdm0-9]+",
    re.IGNORECASE,
)

# Excel and XML 1.0 reject these C0 control characters.  Keep tab, line feed,
# and carriage return out of this pattern: they are valid cell content and
# must survive table export.
TABLE_ILLEGAL_CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def _warning_record(
    code: str,
    *,
    page_no: int,
    message: str | None = None,
    candidate_index: int | None = None,
    table_index: int | None = None,
) -> dict[str, Any]:
    """Build a stable warning record for ``99_result/warnings.jsonl``.

    Page contracts intentionally keep warnings as ``list[str]``.  The richer
    document-level record is assembled separately so exception details never
    become part of the machine-readable warning code.
    """

    record: dict[str, Any] = {"code": code, "page_no": page_no}
    if candidate_index is not None:
        record["candidate_index"] = candidate_index
    if table_index is not None:
        record["table_index"] = table_index
    if message is not None:
        record["message"] = str(message)
    return record


def _require_pdfplumber() -> Any:
    try:
        import pdfplumber  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("PDF Load requires the 'pdfplumber' package") from exc
    return pdfplumber


def _normalise_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")
    # Do not use ``str.strip`` here: it would silently remove valid table
    # content (tab/LF/CR) and prohibited control characters before we can
    # report their removal.
    return text.strip(" ")


def _clean_rows(data: Iterable[Iterable[Any]]) -> list[list[str]]:
    rows = [[_normalise_cell(cell) for cell in row] for row in data]
    rows = [row for row in rows if any(cell for cell in row)]
    if not rows:
        return []
    max_columns = max(len(row) for row in rows)
    rows = [row + [""] * (max_columns - len(row)) for row in rows]
    # Drop columns that are blank in every row; this mirrors the ProSure
    # loader's table cleanup and prevents empty PDF columns leaking to LLMs.
    keep = [index for index in range(max_columns) if any(row[index] for row in rows)]
    return [[row[index] for index in keep] for row in rows]


def _sanitize_table_rows(
    rows: list[list[str]],
) -> tuple[list[list[str]], int, list[dict[str, int]]]:
    """Remove Excel/XML-illegal controls while preserving cell coordinates.

    The parser keeps PDF text untouched; this helper is only applied to the
    values used to create Markdown and XLSX table artifacts.
    """

    removed_count = 0
    affected_cells: list[dict[str, int]] = []
    sanitized_rows: list[list[str]] = []
    for row_no, row in enumerate(rows, start=1):
        sanitized_row: list[str] = []
        for column_no, value in enumerate(row, start=1):
            sanitized_value = TABLE_ILLEGAL_CONTROL_CHARACTER_PATTERN.sub("", value)
            cell_removed_count = len(value) - len(sanitized_value)
            if cell_removed_count:
                removed_count += cell_removed_count
                affected_cells.append(
                    {
                        "row": row_no,
                        "column": column_no,
                        "removed_count": cell_removed_count,
                    }
                )
            sanitized_row.append(sanitized_value)
        sanitized_rows.append(sanitized_row)
    return sanitized_rows, removed_count, affected_cells


def _markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header = rows[0]

    def escaped(value: str) -> str:
        # Markdown rows cannot contain literal line breaks.  Flatten all
        # newline variants here; the sanitizer and XLSX export still receive
        # the original tab/LF/CR characters unchanged.
        value = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        return value.replace("|", r"\|")

    lines = ["| " + " | ".join(escaped(cell) for cell in header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines.extend("| " + " | ".join(escaped(cell) for cell in row) + " |" for row in rows[1:])
    return "\n".join(lines)


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _bbox_area(bbox: list[float]) -> float:
    if len(bbox) < 4:
        return 0.0
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _join_page_objects(objects: list[dict[str, Any]]) -> str:
    """본문은 한 줄, 표·이미지 경계는 빈 줄 하나로 구분한다."""

    parts: list[str] = []
    previous_kind = ""
    for obj in objects:
        content = str(obj.get("content", "")).strip()
        if not content:
            continue
        kind = str(obj.get("kind", "TEXT"))
        if parts:
            block_kinds = {"TABLE", "IMAGE"}
            parts.append(
                "\n\n"
                if previous_kind in block_kinds or kind in block_kinds
                else "\n"
            )
        parts.append(content)
        previous_kind = kind
    return "".join(parts)


def _markdown_text(value: str) -> str:
    """Escape plain PDF body text only when composing Markdown output."""

    return value if SECTION_LINE_PATTERN.search(value) else value.replace("|", r"\|")


def _inside_bbox(x: float, y: float, bbox: tuple[float, float, float, float]) -> bool:
    x0, top, x1, bottom = bbox
    return x0 <= x <= x1 and top <= y <= bottom


def _extract_text_objects(
    page: Any,
    table_bboxes: list[tuple[float, float, float, float]],
    *,
    removed_line_bboxes: list[tuple[float, float, float, float]],
    fallback_text: str,
    words: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """표·반복 헤더·푸터를 제외한 본문 행과 Y 좌표를 반환한다."""

    if words is None:
        try:
            words = page.extract_words() or []
        except Exception:
            words = []
    if not words:
        fallback = fallback_text.strip()
        return [{"y": 0.0, "x": 0.0, "content": fallback, "kind": "TEXT"}] if fallback else []
    words = sorted(words, key=lambda word: (float(word.get("top", 0)), float(word.get("x0", 0))))
    lines: list[list[dict[str, Any]]] = []
    for word in words:
        top = float(word.get("top", 0))
        if not lines or abs(top - float(lines[-1][0].get("top", 0))) > 3:
            lines.append([word])
        else:
            lines[-1].append(word)
    result: list[dict[str, Any]] = []
    for line in lines:
        line.sort(key=lambda word: float(word.get("x0", 0)))
        line_top = min(float(word.get("top", 0)) for word in line)
        line_bottom = max(float(word.get("bottom", 0)) for word in line)
        if any(
            abs(line_top - bbox[1]) <= 3 and abs(line_bottom - bbox[3]) <= 3
            for bbox in removed_line_bboxes
        ):
            continue
        outside: list[dict[str, Any]] = []
        for word in line:
            x = (float(word.get("x0", 0)) + float(word.get("x1", 0))) / 2
            y = (float(word.get("top", 0)) + float(word.get("bottom", 0))) / 2
            if not any(_inside_bbox(x, y, bbox) for bbox in table_bboxes):
                outside.append(word)
        if outside:
            top = min(float(word.get("top", 0)) for word in outside)
            text = " ".join(str(word.get("text", "")) for word in outside).strip()
            if text:
                result.append(
                    {
                        "y": top,
                        "x": min(float(word.get("x0", 0)) for word in outside),
                        "content": text,
                        "kind": "TEXT",
                    }
                )
    return result


def _page_quality(
    page: Any,
    raw_text: str,
    *,
    extraction_failed: bool = False,
    quality_text: str | None = None,
    table_present: bool = False,
    words: list[dict[str, Any]] | None = None,
) -> tuple[int, int, int, float, PageStatus]:
    # OCR 품질용 문자수는 표와 반복 헤더·푸터를 제외한 본문에 대해서만
    # 계산한다.  ``quality_text``가 없으면 기존 직접 호출 호환을 위해
    # 원문을 사용한다.
    meaningful_count = len(
        MEANINGFUL_CHARACTER_PATTERN.findall(raw_text if quality_text is None else quality_text)
    )
    if words is not None:
        word_count = len(words)
    else:
        try:
            word_count = len(page.extract_words() or [])
        except Exception:
            word_count = len(raw_text.split())

    images = list(getattr(page, "images", []) or [])
    page_area = float(getattr(page, "width", 0) or 0) * float(getattr(page, "height", 0) or 0)
    largest_ratio = 0.0
    if page_area > 0:
        for image in images:
            width = max(0.0, float(image.get("x1", 0)) - float(image.get("x0", 0)))
            top = float(image.get("top", image.get("y0", 0)))
            bottom = float(image.get("bottom", image.get("y1", 0)))
            height = abs(bottom - top)
            largest_ratio = max(largest_ratio, min(1.0, width * height / page_area))

    if extraction_failed:
        status = PageStatus.OCR_REQUIRED
    elif (
        not table_present
        and meaningful_count <= OCR_MINIMUM_CHARACTERS
        and largest_ratio >= OCR_IMAGE_AREA_RATIO
    ):
        status = PageStatus.OCR_REQUIRED
    elif meaningful_count == 0 and not table_present and largest_ratio < OCR_IMAGE_AREA_RATIO:
        status = PageStatus.EMPTY
    else:
        status = PageStatus.TEXT
    return meaningful_count, word_count, len(images), largest_ratio, status


def _save_xlsx(path: Path, rows: list[list[str]]) -> str | None:
    try:
        from openpyxl import Workbook  # type: ignore
    except ImportError:  # pragma: no cover - optional dependency
        return None
    workbook = Workbook()
    worksheet = workbook.active
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    return str(path)


def _crop_pdf(
    source_pdf: Path,
    output_path: Path,
    removed_lines: list[dict[str, Any]],
) -> Path | None:
    try:
        import pymupdf  # type: ignore
    except ImportError:  # pragma: no cover - optional dependency
        return None
    source = pymupdf.open(str(source_pdf))
    result = pymupdf.open()
    try:
        for page in source:
            width, height = page.rect.width, page.rect.height
            page_lines = [
                line for line in removed_lines if int(line["page_no"]) == page.number + 1
            ]
            header_bottoms = [
                float(line["bbox"][3]) for line in page_lines if line["location"] == "HEADER"
            ]
            footer_tops = [
                float(line["bbox"][1]) for line in page_lines if line["location"] == "FOOTER"
            ]
            y0 = max([0.0, *header_bottoms])
            y1 = min([height, *footer_tops])
            if y1 <= y0:
                y0, y1 = 0.0, height
            new_page = result.new_page(width=width, height=y1 - y0)
            new_page.show_pdf_page(
                new_page.rect,
                source,
                page.number,
                clip=pymupdf.Rect(0, y0, width, y1),
            )
        result.save(str(output_path))
    finally:
        result.close()
        source.close()
    return output_path


class ProSurePdfParser:
    """Parse a PDF and persist all intermediate artifacts under ``output_dir``."""

    parser_version = PARSER_VERSION

    def __init__(
        self,
        *,
        header_footer_enabled: bool = False,
        table_reconstructor: TableReconstructor | None = None,
    ) -> None:
        self.header_footer_enabled = header_footer_enabled
        self.table_reconstructor = table_reconstructor

    def parse(self, source_pdf: Path, item_dir: Path) -> PdfParseOutput:
        source_pdf = Path(source_pdf)
        output_dir = Path(item_dir)
        if not source_pdf.is_file():
            raise FileNotFoundError(source_pdf)
        output_dir.mkdir(parents=True, exist_ok=True)
        tables_dir = output_dir / "02_tables"
        processed_tables_dir = output_dir / "03_processed" / "tables"
        debug_dir = output_dir / "90_debug"
        for directory in (tables_dir, processed_tables_dir, debug_dir):
            directory.mkdir(parents=True, exist_ok=True)

        images, image_occurrences_by_page, warnings = extract_embedded_images(
            source_pdf,
            output_dir,
        )
        pdfplumber = _require_pdfplumber()
        with pdfplumber.open(str(source_pdf)) as pdf, ExitStack() as renderer_stack:
            table_renderer: TableRegionRenderer | None = None
            table_renderer_open_error: Exception | None = None
            # 헤더·푸터 분석과 본문 조립에서 같은 단어 추출을 반복하지 않는다.
            words_by_page: dict[int, list[dict[str, Any]]] = {}
            for page_index, page in enumerate(pdf.pages, start=1):
                try:
                    words_by_page[page_index] = page.extract_words() or []
                except Exception:
                    words_by_page[page_index] = []
            analysis = analyze_header_footer(
                pdf,
                enabled=self.header_footer_enabled,
                words_by_page=words_by_page,
            )
            repeated_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
            for removed_line in analysis["removed_lines"]:
                repeated_by_page.setdefault(int(removed_line["page_no"]), []).append(
                    tuple(float(value) for value in removed_line["bbox"])
                )
            pages: list[ParsedPage] = []
            tables: list[ParsedTable] = []
            rejected_table_count = 0
            markdown_pages: list[str] = []
            raw_pages: list[str] = []
            for page_index, page in enumerate(pdf.pages, start=1):
                page_warnings: list[str] = []
                page_warning_records: list[dict[str, Any]] = []
                try:
                    raw = str(page.extract_text() or "")
                except Exception as exc:
                    raw = ""
                    page_warnings.append("TEXT_EXTRACTION_FAILED")
                    page_warning_records.append(
                        _warning_record(
                            "TEXT_EXTRACTION_FAILED",
                            page_no=page_index,
                            message=str(exc),
                        )
                    )
                page_tables: list[str] = []
                page_table_objects: list[dict[str, Any]] = []
                table_bboxes: list[tuple[float, float, float, float]] = []
                try:
                    found_tables = page.find_tables()
                except Exception as exc:
                    found_tables = []
                    page_warnings.append("TABLE_DETECTION_FAILED")
                    page_warning_records.append(
                        _warning_record(
                            "TABLE_DETECTION_FAILED",
                            page_no=page_index,
                            message=str(exc),
                        )
                    )
                table_candidates: list[dict[str, Any]] = []
                for candidate_index, table in enumerate(found_tables, start=1):
                    try:
                        rows = _clean_rows(table.extract())
                    except Exception as exc:
                        page_warnings.append("TABLE_EXTRACTION_FAILED")
                        page_warning_records.append(
                            _warning_record(
                                "TABLE_EXTRACTION_FAILED",
                                page_no=page_index,
                                candidate_index=candidate_index,
                                message=str(exc),
                            )
                        )
                        continue
                    rows, removed_count, affected_cells = _sanitize_table_rows(rows)
                    bbox = [float(value) for value in getattr(table, "bbox", (0, 0, 0, 0))]
                    table_candidates.append(
                        {
                            "candidate_index": candidate_index,
                            "rows": rows,
                            "bbox": bbox,
                            "removed_count": removed_count,
                            "affected_cells": affected_cells,
                            "assessment": assess_table(
                                rows,
                                bbox=bbox,
                                page_height=float(page.height),
                            ),
                        }
                    )

                # pdfplumber can report the same ruled area more than once.
                # Reject only near-identical overlaps; separate tables with the
                # same values remain independent records.
                for index, candidate in enumerate(table_candidates):
                    assessment: TableAssessment = candidate["assessment"]
                    if assessment.status is TableQualityStatus.REJECTED:
                        continue
                    fingerprint = table_fingerprint(candidate["rows"])
                    for previous in table_candidates[:index]:
                        previous_assessment: TableAssessment = previous["assessment"]
                        if previous_assessment.status is TableQualityStatus.REJECTED:
                            continue
                        if (
                            fingerprint
                            and fingerprint == table_fingerprint(previous["rows"])
                            and overlap_ratio(candidate["bbox"], previous["bbox"]) >= 0.95
                        ):
                            candidate["assessment"] = TableAssessment(
                                TableQualityStatus.REJECTED,
                                "DUPLICATE_TABLE",
                                assessment.metrics,
                            )
                            break

                # A one-dimensional child candidate is often just a merged
                # label already present in a meaningful outer table.  Genuine
                # nested 2-D tables are retained even when their bbox is inside
                # the outer table.
                for candidate in table_candidates:
                    assessment = candidate["assessment"]
                    if assessment.status is not TableQualityStatus.FRAGMENT:
                        continue
                    if assessment.metrics.column_count != 1:
                        continue
                    child_fingerprint = table_text_fingerprint(candidate["rows"])
                    if not child_fingerprint:
                        continue
                    for parent in table_candidates:
                        if parent is candidate:
                            continue
                        parent_assessment: TableAssessment = parent["assessment"]
                        if parent_assessment.status is not TableQualityStatus.MEANINGFUL:
                            continue
                        parent_fingerprint = table_text_fingerprint(parent["rows"])
                        if (
                            bbox_contains(parent["bbox"], candidate["bbox"])
                            and child_fingerprint in parent_fingerprint
                        ):
                            candidate["assessment"] = TableAssessment(
                                TableQualityStatus.REJECTED,
                                "NESTED_TEXT_DUPLICATE",
                                assessment.metrics,
                            )
                            break

                # Assign stable output IDs before reconstruction so bbox containment
                # can reference the final table IDs.  Containment is only page-local;
                # equal headers or adjacent pages are never merged.
                accepted_candidates = [
                    candidate
                    for candidate in table_candidates
                    if candidate["assessment"].status
                    is not TableQualityStatus.REJECTED
                ]
                for saved_index, candidate in enumerate(
                    accepted_candidates, start=1
                ):
                    candidate["saved_table_index"] = saved_index
                    candidate["fragment_id"] = (
                        f"page_{page_index:04d}_table_{saved_index:03d}"
                    )
                for child in accepted_candidates:
                    containing = [
                        parent
                        for parent in accepted_candidates
                        if parent is not child
                        and _bbox_area(parent["bbox"]) > _bbox_area(child["bbox"])
                        and bbox_contains(parent["bbox"], child["bbox"])
                    ]
                    parent = min(
                        containing,
                        key=lambda candidate: _bbox_area(candidate["bbox"]),
                        default=None,
                    )
                    child["contained_by"] = (
                        str(parent["fragment_id"]) if parent is not None else None
                    )
                parent_ids = {
                    str(candidate["contained_by"])
                    for candidate in accepted_candidates
                    if candidate.get("contained_by")
                }

                for candidate in table_candidates:
                    candidate_index = int(candidate["candidate_index"])
                    rows = candidate["rows"]
                    bbox = candidate["bbox"]
                    removed_count = int(candidate["removed_count"])
                    affected_cells = candidate["affected_cells"]
                    assessment = candidate["assessment"]
                    if assessment.status is TableQualityStatus.REJECTED:
                        rejected_table_count += 1
                        warnings.append(
                            rejection_warning(
                                page_no=page_index,
                                candidate_index=candidate_index,
                                bbox=bbox,
                                assessment=assessment,
                            )
                        )
                        continue

                    saved_table_index = int(candidate["saved_table_index"])
                    table_bboxes.append(tuple(bbox))
                    fragment_id = str(candidate["fragment_id"])
                    if removed_count:
                        warnings.append(
                            {
                                "code": "TABLE_ILLEGAL_CONTROL_CHARACTERS_REMOVED",
                                "page_no": page_index,
                                "table_id": fragment_id,
                                "table_index": saved_table_index,
                                "candidate_index": candidate_index,
                                "removed_count": removed_count,
                                "affected_cells": affected_cells,
                            }
                        )
                    md_path = tables_dir / f"{fragment_id}.md"
                    markdown = _markdown_table(rows)
                    md_path.write_text(markdown, encoding="utf-8")
                    xlsx_path = _save_xlsx(tables_dir / f"{fragment_id}.xlsx", rows)
                    rendered_image_path = ""
                    rendered_path = tables_dir / f"{fragment_id}.png"
                    try:
                        if table_renderer_open_error is not None:
                            raise table_renderer_open_error
                        if table_renderer is None:
                            try:
                                table_renderer = renderer_stack.enter_context(
                                    TableRegionRenderer(source_pdf)
                                )
                            except Exception as exc:
                                table_renderer_open_error = exc
                                raise
                        table_renderer.render(
                            page_no=page_index,
                            bbox=bbox,
                            output_path=rendered_path,
                        )
                        rendered_image_path = rendered_path.relative_to(
                            output_dir
                        ).as_posix()
                    except Exception as exc:
                        page_warnings.append("TABLE_RENDER_FAILED")
                        page_warning_records.append(
                            _warning_record(
                                "TABLE_RENDER_FAILED",
                                page_no=page_index,
                                table_index=saved_table_index,
                                candidate_index=candidate_index,
                                message=str(exc),
                            )
                        )
                    contained_by = candidate.get("contained_by")
                    included_in_page = contained_by is None
                    nested = bool(contained_by or fragment_id in parent_ids)
                    processed_path = processed_tables_dir / f"{fragment_id}.md"
                    processed_relative = processed_path.relative_to(
                        output_dir
                    ).as_posix()
                    reconstruction: dict[str, Any]
                    final_markdown = markdown
                    if assessment.status is not TableQualityStatus.MEANINGFUL:
                        reconstruction = {
                            "status": "SKIPPED_NOT_MEANINGFUL",
                            "representation_mode": None,
                            "output_path": processed_relative,
                            "response_path": None,
                            "model": None,
                            "prompt_version": None,
                            "attempts": 0,
                            "error_code": None,
                        }
                    elif self.table_reconstructor is None:
                        reconstruction = {
                            "status": "PASSTHROUGH_DISABLED",
                            "representation_mode": None,
                            "output_path": processed_relative,
                            "response_path": None,
                            "model": None,
                            "prompt_version": None,
                            "attempts": 0,
                            "error_code": None,
                        }
                    else:
                        representation_mode = select_representation_mode(
                            rows,
                            nested=nested,
                        )
                        response_path = processed_tables_dir / (
                            f"{fragment_id}.response.json"
                        )
                        result = self.table_reconstructor.reconstruct(
                            table_id=fragment_id,
                            source_markdown=markdown,
                            image_path=rendered_path,
                            representation_mode=representation_mode,
                            markdown_input_path=md_path.relative_to(
                                output_dir
                            ).as_posix(),
                            image_input_path=rendered_path.relative_to(
                                output_dir
                            ).as_posix(),
                            final_markdown_path=processed_relative,
                        )
                        final_markdown = result.final_markdown
                        response_relative: str | None = None
                        if result.attempts:
                            result.write_json(response_path)
                            response_relative = response_path.relative_to(
                                output_dir
                            ).as_posix()
                        last_error = next(
                            (
                                attempt.error
                                for attempt in reversed(result.attempts)
                                if attempt.error
                            ),
                            None,
                        )
                        reconstruction = {
                            "status": result.final_status.value,
                            "representation_mode": result.representation_mode.value,
                            "output_path": processed_relative,
                            "response_path": response_relative,
                            "model": result.model,
                            "prompt_version": result.prompt_version,
                            "attempts": len(result.attempts),
                            "error_code": (
                                last_error.get("code") if last_error else None
                            ),
                        }
                        if result.final_status is ReconstructionStatus.FALLBACK:
                            page_warnings.append("TABLE_RECONSTRUCTION_FALLBACK")
                            page_warning_records.append(
                                _warning_record(
                                    "TABLE_RECONSTRUCTION_FALLBACK",
                                    page_no=page_index,
                                    table_index=saved_table_index,
                                    message=(
                                        last_error.get("message")
                                        if last_error
                                        else "표 이미지가 없어 LLM을 호출하지 못했습니다."
                                    ),
                                )
                            )
                    _write_text_atomic(processed_path, final_markdown)
                    parsed_table = ParsedTable(
                        table_id=fragment_id,
                        page_no=page_index,
                        table_index=saved_table_index,
                        bbox=bbox,
                        row_count=len(rows),
                        column_count=len(rows[0]),
                        markdown_path=md_path.relative_to(output_dir).as_posix(),
                        xlsx_path=(
                            Path(xlsx_path).relative_to(output_dir).as_posix()
                            if xlsx_path
                            else ""
                        ),
                        rendered_image_path=rendered_image_path,
                        processed_markdown_path=processed_relative,
                        contained_by=(str(contained_by) if contained_by else None),
                        included_in_page=included_in_page,
                        reconstruction=reconstruction,
                        quality_status=assessment.status,
                        quality_reason=assessment.reason,
                    )
                    tables.append(parsed_table)
                    page_tables.append(fragment_id)
                    if included_in_page:
                        page_table_objects.append(
                            {
                                "y": bbox[1],
                                "x": bbox[0],
                                "content": final_markdown,
                                "kind": "TABLE",
                            }
                        )
                text_objects = _extract_text_objects(
                    page,
                    table_bboxes,
                    removed_line_bboxes=(
                        repeated_by_page.get(page_index, [])
                        if self.header_footer_enabled
                        else []
                    ),
                    fallback_text=raw,
                    words=words_by_page.get(page_index, []),
                )
                text_content = "\n".join(obj["content"] for obj in text_objects).strip()
                # 품질 판정에서는 옵션과 무관하게 반복 행을 제외한다.  표가
                # 성공적으로 추출된 경우 표 영역의 PDF 텍스트도 중복으로
                # 세지 않는다.
                quality_text_objects = _extract_text_objects(
                    page,
                    table_bboxes,
                    removed_line_bboxes=repeated_by_page.get(page_index, []),
                    fallback_text=raw,
                    words=words_by_page.get(page_index, []),
                )
                quality_text = "\n".join(
                    obj["content"] for obj in quality_text_objects
                ).strip()
                page_image_objects = [
                    {
                        "y": occurrence["bbox"][1],
                        "x": occurrence["bbox"][0],
                        "content": (
                            f"> 이미지 참조: {occurrence['image_id']} "
                            f"({occurrence['image_path']})"
                        ),
                        "kind": "IMAGE",
                    }
                    for occurrence in image_occurrences_by_page.get(page_index, [])
                ]
                markdown_text_objects = [
                    {**obj, "content": _markdown_text(str(obj["content"]))}
                    for obj in text_objects
                ]
                page_objects = [
                    *markdown_text_objects,
                    *page_table_objects,
                    *page_image_objects,
                ]
                page_objects.sort(
                    key=lambda obj: (float(obj["y"]), float(obj.get("x", 0.0)))
                )
                page_view = _join_page_objects(page_objects)
                quality = _page_quality(
                    page,
                    raw,
                    extraction_failed=any(
                        warning == "TEXT_EXTRACTION_FAILED" for warning in page_warnings
                    ),
                    quality_text=quality_text,
                    table_present=bool(page_tables),
                    words=words_by_page.get(page_index, []),
                )
                pages.append(
                    ParsedPage(
                        page_no=page_index,
                        width=float(page.width),
                        height=float(page.height),
                        text_raw=raw,
                        text_content=text_content,
                        content_markdown=page_view,
                        meaningful_character_count=quality[0],
                        word_count=quality[1],
                        image_count=quality[2],
                        largest_image_area_ratio=quality[3],
                        page_status=quality[4],
                        table_refs=page_tables,
                        image_refs=[
                            occurrence["image_id"]
                            for occurrence in image_occurrences_by_page.get(page_index, [])
                        ],
                        warnings=page_warnings,
                    )
                )
                warnings.extend(
                    page_warning_records
                )
                raw_pages.append(raw)
                markdown_pages.append(f"page_{page_index}\n\n{page_view}" if page_view else "")

        cropped_path = None
        if analysis["enabled"] and analysis["applied"]:
            try:
                created_cropped_path = _crop_pdf(
                    source_pdf,
                    debug_dir / "cropped.pdf",
                    analysis["removed_lines"],
                )
                if created_cropped_path is None:
                    warnings.append(
                        {"code": "CROPPED_PDF_UNAVAILABLE", "message": "PyMuPDF가 필요합니다."}
                    )
                else:
                    cropped_path = created_cropped_path.relative_to(output_dir)
            except Exception as exc:
                warnings.append({"code": "CROPPED_PDF_FAILED", "message": str(exc)})
        raw_text = "\f".join(raw_pages)
        content = "\n\n---\n\n".join(item for item in markdown_pages if item)
        return PdfParseOutput(
            pages=pages,
            tables=tables,
            images=images,
            raw_text=raw_text,
            content_markdown=content,
            cropped_pdf_path=cropped_path,
            header_footer_analysis=analysis,
            warnings=warnings,
            rejected_table_count=rejected_table_count,
            table_reconstruction_enabled=self.table_reconstructor is not None,
        )
