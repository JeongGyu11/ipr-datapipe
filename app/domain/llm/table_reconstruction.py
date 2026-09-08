"""표 재구성 LLM 도메인 모델과 순수 Markdown 검증기.

이 모듈은 PDF 파서나 파일 저장소에 의존하지 않는다. 호출 여부와 입력
파일의 존재는 상위 애플리케이션이 결정하고, 여기서는 한 표의 요청,
검증, 재시도와 감사 가능한 결과 모델만 책임진다.
"""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol


STRUCTURED_EMPTY_CELL_RATIO = 0.25
STRUCTURED_MAX_CELL_LENGTH = 120


class RepresentationMode(StrEnum):
    MARKDOWN_TABLE = "MARKDOWN_TABLE"
    STRUCTURED_MARKDOWN = "STRUCTURED_MARKDOWN"


class ReconstructionStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FALLBACK = "FALLBACK"


class AttemptOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    HTTP_ERROR = "HTTP_ERROR"
    REQUEST_ERROR = "REQUEST_ERROR"


class TableResponseError(ValueError):
    """LLM이 반환한 텍스트가 표 재구성 계약을 위반할 때 발생한다."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class AttemptRecord:
    attempt_no: int
    outcome: AttemptOutcome
    http_status: int | None = None
    response: Any | None = None
    response_raw: str | None = None
    error: dict[str, str] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["outcome"] = self.outcome.value
        return payload


@dataclass
class ReconstructionResult:
    schema_version: str
    table_id: str
    representation_mode: RepresentationMode
    model: str
    prompt_version: str
    inputs: dict[str, str]
    attempts: list[AttemptRecord] = field(default_factory=list)
    selected_attempt: int | None = None
    final_status: ReconstructionStatus = ReconstructionStatus.FALLBACK
    final_markdown: str = ""
    final_markdown_path: str | None = None

    @property
    def status(self) -> ReconstructionStatus:
        """통합 계층에서 간결하게 사용할 수 있는 최종 상태 별칭."""
        return self.final_status

    @property
    def markdown(self) -> str:
        """최종적으로 페이지에 사용할 Markdown 별칭."""
        return self.final_markdown

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "table_id": self.table_id,
            "representation_mode": self.representation_mode.value,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "inputs": dict(self.inputs),
            "attempts": [attempt.as_dict() for attempt in self.attempts],
            "selected_attempt": self.selected_attempt,
            "final_status": self.final_status.value,
            "final_markdown_path": self.final_markdown_path,
        }

    def write_json(self, path: str | Path) -> None:
        """결과를 임시 파일 후 교체하여 원자적으로 기록한다."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(self.as_dict(), ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)


class TableReconstructor(Protocol):
    """Minimal service contract consumed by the PDF parser."""

    def reconstruct(
        self,
        *,
        table_id: str,
        source_markdown: str,
        image_path: str | Path,
        representation_mode: RepresentationMode,
        markdown_input_path: str | None = None,
        image_input_path: str | None = None,
        final_markdown_path: str | None = None,
    ) -> ReconstructionResult: ...


class ChatCompletionTransport(Protocol):
    """httpx.Client와 동일한 최소 POST 인터페이스."""

    def post(self, url: str, **kwargs: Any) -> Any: ...


_NUMBER_TOKEN = re.compile(
    r"(?<!\d)[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?"
)
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^\s*(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)(?:[-*+] |\d+[.)] )(.*)$")
_SEMANTIC_SYMBOLS = frozenset("%％‰₩$€¥")


def _number_tokens(text: str) -> Counter[str]:
    return Counter(match.group(0) for match in _NUMBER_TOKEN.finditer(text))


def _split_markdown_row(line: str) -> list[str]:
    """Split a row on unescaped pipes (cell text may contain ``\\|``)."""
    content = line.strip()
    if content.startswith("|"):
        content = content[1:]
    if content.endswith("|") and not content.endswith("\\|"):
        content = content[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in content:
        if char == "|" and not escaped:
            cells.append("".join(current))
            current = []
            escaped = False
            continue
        current.append(char)
        if char == "\\" and not escaped:
            escaped = True
        else:
            escaped = False
    cells.append("".join(current))
    return cells


def _markdown_content_rows(text: str) -> list[list[str]]:
    """Markdown 표에서 구분 행을 제외한 셀 데이터만 반환한다."""

    return [
        _split_markdown_row(line)
        for line in text.splitlines()
        if "|" in line and not _TABLE_SEPARATOR.match(line)
    ]


def _semantic_text(value: str) -> str:
    """표현용 공백·문장부호를 제외하고 데이터 의미 문자를 정규화한다."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        char for char in normalized if char.isalnum() or char in _SEMANTIC_SYMBOLS
    )


def _source_content(source_markdown: str) -> tuple[list[list[str]], str]:
    rows = _markdown_content_rows(source_markdown)
    if rows:
        return rows, "".join(_semantic_text(cell) for row in rows for cell in row)
    return [], _semantic_text(source_markdown)


def _response_content(markdown: str, mode: RepresentationMode) -> str:
    if mode is RepresentationMode.MARKDOWN_TABLE:
        rows = _markdown_content_rows(markdown)
        return "".join(_semantic_text(cell) for row in rows for cell in row)
    return _semantic_text(markdown)


def _structured_relation_blocks(markdown: str) -> list[tuple[str, str | None]]:
    """설명형 Markdown의 불릿 하위 트리와 제목 구역을 관계 검증 단위로 만든다."""

    lines = [line for line in markdown.splitlines() if line.strip()]
    blocks: list[tuple[str, str | None]] = []
    for index, line in enumerate(lines):
        bullet = _BULLET.match(line)
        if bullet:
            indent = len(bullet.group(1).expandtabs(4))
            end = index + 1
            while end < len(lines):
                if _HEADING.match(lines[end]):
                    break
                next_bullet = _BULLET.match(lines[end])
                if next_bullet and len(next_bullet.group(1).expandtabs(4)) <= indent:
                    break
                end += 1
            blocks.append((_semantic_text("\n".join(lines[index:end])), None))

        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            end = index + 1
            while end < len(lines):
                next_heading = _HEADING.match(lines[end])
                if next_heading and len(next_heading.group(1)) <= level:
                    break
                end += 1
            blocks.append(
                (
                    _semantic_text("\n".join(lines[index:end])),
                    _semantic_text(heading.group(2)),
                )
            )
    return blocks


def _validate_content_preservation(
    source_markdown: str,
    response_markdown: str,
    mode: RepresentationMode,
) -> None:
    """문자 보존과 원본 데이터 행의 항목-값 관계를 검증한다."""

    source_rows, source_content = _source_content(source_markdown)
    response_content = _response_content(response_markdown, mode)
    source_characters = Counter(source_content)
    response_characters = Counter(response_content)
    if source_characters != response_characters:
        missing = list((source_characters - response_characters).elements())
        added = list((response_characters - source_characters).elements())
        raise TableResponseError(
            "CONTENT_CHARACTER_MISMATCH",
            f"원본 의미 문자 불일치: 누락={missing!r}, 추가={added!r}",
        )

    source_cells = Counter(
        _semantic_text(cell)
        for row in source_rows
        for cell in row
        if _semantic_text(cell)
    )
    missing_cells = [
        cell
        for cell, required_count in source_cells.items()
        if response_content.count(cell) < required_count
    ]
    if missing_cells:
        raise TableResponseError(
            "CELL_CONTENT_MISMATCH",
            f"원본 셀 내용을 연속된 데이터로 확인할 수 없습니다: {missing_cells!r}",
        )

    # 첫 행은 표 헤더이므로 데이터 행의 항목-값 관계에서 제외한다.
    source_data_rows = source_rows[1:]
    if mode is RepresentationMode.MARKDOWN_TABLE:
        relation_blocks = [
            (_semantic_text("".join(row)), None)
            for row in _markdown_content_rows(response_markdown)[1:]
        ]
    else:
        relation_blocks = _structured_relation_blocks(response_markdown)

    for row_index, row in enumerate(source_data_rows, start=2):
        cells = [_semantic_text(cell) for cell in row]
        cells = [cell for cell in cells if cell]
        if len(cells) < 2:
            continue
        relation_preserved = False
        for block, heading_anchor in relation_blocks:
            if heading_anchor is not None and not any(
                cell == heading_anchor or cell in heading_anchor or heading_anchor in cell
                for cell in cells
            ):
                continue
            if all(cell in block for cell in cells):
                relation_preserved = True
                break
        if not relation_preserved:
            raise TableResponseError(
                "ROW_RELATION_MISMATCH",
                f"원본 {row_index}행의 항목-값 관계를 확인할 수 없습니다",
            )


def validate_markdown_response(
    markdown: str,
    mode: RepresentationMode,
    *,
    source_markdown: str = "",
) -> str:
    """검증된 순수 Markdown을 반환하고, 계약 위반 시 명시적 오류를 낸다."""
    mode = RepresentationMode(mode)
    if not isinstance(markdown, str) or not markdown.strip():
        raise TableResponseError("EMPTY_RESPONSE", "LLM 응답이 비어 있습니다")
    text = markdown.strip()
    if any(_FENCE.match(line) for line in text.splitlines()):
        raise TableResponseError("CODE_FENCE", "코드 펜스가 포함된 응답입니다")

    lines = [line for line in text.splitlines() if line.strip()]
    if mode is RepresentationMode.MARKDOWN_TABLE:
        pipe_lines = [line for line in lines if "|" in line]
        if len(pipe_lines) != len(lines):
            raise TableResponseError(
                "INVALID_MARKDOWN", "Markdown 표 이외의 설명이 포함되어 있습니다"
            )
        separator_indexes = [idx for idx, line in enumerate(lines) if _TABLE_SEPARATOR.match(line)]
        if not pipe_lines or not separator_indexes:
            raise TableResponseError("INVALID_MARKDOWN", "Markdown 표와 구분 행이 필요합니다")
        sep_index = separator_indexes[0]
        if sep_index == 0:
            raise TableResponseError("INVALID_MARKDOWN", "Markdown 표 헤더가 없습니다")
        if sep_index >= len(lines) - 1:
            raise TableResponseError("INVALID_MARKDOWN", "Markdown 표 데이터 행이 없습니다")
        expected_columns = len(_split_markdown_row(lines[sep_index]))
        if expected_columns < 1:
            raise TableResponseError("INVALID_MARKDOWN", "표 열 수를 판정할 수 없습니다")
        for line in pipe_lines:
            if _TABLE_SEPARATOR.match(line):
                continue
            count = len(_split_markdown_row(line))
            if count != expected_columns:
                raise TableResponseError("INVALID_MARKDOWN", "표의 열 수가 일정하지 않습니다")
    else:
        if any(_TABLE_SEPARATOR.match(line) for line in lines):
            raise TableResponseError(
                "INVALID_MARKDOWN", "설명형 응답에는 Markdown 표를 사용할 수 없습니다"
            )
        has_heading = any(line.lstrip().startswith("#") for line in lines)
        has_bullet = any(re.match(r"^\s*(?:[-*+] |\d+[.)] )", line) for line in lines)
        if not (has_heading and has_bullet):
            raise TableResponseError("INVALID_MARKDOWN", "제목과 불릿 구조가 필요합니다")

    if source_markdown:
        source_numbers = _number_tokens(source_markdown)
        response_numbers = _number_tokens(text)
        if source_numbers != response_numbers:
            missing = list((source_numbers - response_numbers).elements())
            added = list((response_numbers - source_numbers).elements())
            details = f"누락={missing!r}, 추가={added!r}"
            raise TableResponseError("NUMERIC_TOKEN_MISMATCH", details)
        _validate_content_preservation(source_markdown, text, mode)
    return text


def select_representation_mode(
    rows: list[list[str]],
    *,
    nested: bool = False,
) -> RepresentationMode:
    """Apply the deliberately small v1 routing rule before invoking the LLM."""

    if nested:
        return RepresentationMode.STRUCTURED_MARKDOWN
    cells = [str(cell) for row in rows for cell in row]
    if cells:
        empty_ratio = sum(not cell.strip() for cell in cells) / len(cells)
        if empty_ratio >= STRUCTURED_EMPTY_CELL_RATIO:
            return RepresentationMode.STRUCTURED_MARKDOWN
        longest = max(
            len(re.sub(r"\s+", " ", cell).strip()) for cell in cells
        )
        if longest >= STRUCTURED_MAX_CELL_LENGTH:
            return RepresentationMode.STRUCTURED_MARKDOWN
    return RepresentationMode.MARKDOWN_TABLE


__all__ = [
    "AttemptOutcome",
    "AttemptRecord",
    "ChatCompletionTransport",
    "ReconstructionResult",
    "ReconstructionStatus",
    "RepresentationMode",
    "STRUCTURED_EMPTY_CELL_RATIO",
    "STRUCTURED_MAX_CELL_LENGTH",
    "TableResponseError",
    "TableReconstructor",
    "validate_markdown_response",
    "select_representation_mode",
]
