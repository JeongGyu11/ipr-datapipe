from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.llm.table_reconstruction import (
    AttemptOutcome,
    ReconstructionStatus,
    RepresentationMode,
    TableResponseError,
    select_representation_mode,
    validate_markdown_response,
)
from app.infrastructure.llm.table_reconstruction_client import TableReconstructionService


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self.payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


SOURCE_TABLE = "| 항목 | 금액 |\n| --- | --- |\n| 기본 | 10,000원 |"
VALID_TABLE = "| 항목 | 금액 |\n| --- | --- |\n| 기본 | 10,000원 |"
VALID_STRUCTURED = "# 항목\n- 기본 금액: 10,000원"


def test_validate_markdown_table_and_numeric_tokens():
    assert validate_markdown_response(VALID_TABLE, RepresentationMode.MARKDOWN_TABLE, source_markdown=SOURCE_TABLE)
    with pytest.raises(TableResponseError) as exc:
        validate_markdown_response("| 항목 | 금액 |\n| --- | --- |\n| 기본 | 20,000원 |", RepresentationMode.MARKDOWN_TABLE, source_markdown=SOURCE_TABLE)
    assert exc.value.code == "NUMERIC_TOKEN_MISMATCH"


def test_validation_rejects_deleted_text_only_row():
    source = "| 항목 | 내용 |\n| --- | --- |\n| 안내 | 계약 전 확인 |"
    deleted = "| 항목 | 내용 |\n| --- | --- |\n| 안내 | |"

    with pytest.raises(TableResponseError) as exc:
        validate_markdown_response(
            deleted,
            RepresentationMode.MARKDOWN_TABLE,
            source_markdown=source,
        )

    assert exc.value.code == "CONTENT_CHARACTER_MISMATCH"


def test_validation_rejects_changed_unit_even_when_number_is_preserved():
    source = "| 항목 | 기간 |\n| --- | --- |\n| 대기기간 | 10개월 |"
    changed = "| 항목 | 기간 |\n| --- | --- |\n| 대기기간 | 10년 |"

    with pytest.raises(TableResponseError) as exc:
        validate_markdown_response(
            changed,
            RepresentationMode.MARKDOWN_TABLE,
            source_markdown=source,
        )

    assert exc.value.code == "CONTENT_CHARACTER_MISMATCH"


def test_validation_rejects_reordered_text_inside_a_cell():
    source = "| 항목 | 내용 |\n| --- | --- |\n| 안내 | 계약 전 확인 |"
    reordered = "| 항목 | 내용 |\n| --- | --- |\n| 안내 | 전 계약 확인 |"

    with pytest.raises(TableResponseError) as exc:
        validate_markdown_response(
            reordered,
            RepresentationMode.MARKDOWN_TABLE,
            source_markdown=source,
        )

    assert exc.value.code == "CELL_CONTENT_MISMATCH"


def test_validation_rejects_swapped_item_value_relations():
    source = (
        "| 항목 | 금액 |\n| --- | --- |\n"
        "| 입원 | 10만원 |\n| 수술 | 20만원 |"
    )
    swapped = (
        "| 항목 | 금액 |\n| --- | --- |\n"
        "| 입원 | 20만원 |\n| 수술 | 10만원 |"
    )

    with pytest.raises(TableResponseError) as exc:
        validate_markdown_response(
            swapped,
            RepresentationMode.MARKDOWN_TABLE,
            source_markdown=source,
        )

    assert exc.value.code == "ROW_RELATION_MISMATCH"


def test_structured_validation_rejects_swapped_item_value_relations():
    source = (
        "| 항목 | 금액 |\n| --- | --- |\n"
        "| 입원 | 10만원 |\n| 수술 | 20만원 |"
    )
    swapped = "# 항목 금액\n- 입원: 20만원\n- 수술: 10만원"

    with pytest.raises(TableResponseError) as exc:
        validate_markdown_response(
            swapped,
            RepresentationMode.STRUCTURED_MARKDOWN,
            source_markdown=source,
        )

    assert exc.value.code == "ROW_RELATION_MISMATCH"


def test_validation_rejects_header_only_table():
    with pytest.raises(TableResponseError) as exc:
        validate_markdown_response(
            "| 항목 | 내용 |\n| --- | --- |",
            RepresentationMode.MARKDOWN_TABLE,
            source_markdown="| 항목 | 내용 |\n| --- | --- |\n| 안내 | 확인 |",
        )

    assert exc.value.code == "INVALID_MARKDOWN"


def test_numeric_validation_covers_numbers_touching_korean_units():
    source = "| 항목 | 금액 |\n| --- | --- |\n| 기본 | 10만원 |"
    changed = "| 항목 | 금액 |\n| --- | --- |\n| 기본 | 20만원 |"

    with pytest.raises(TableResponseError) as exc:
        validate_markdown_response(
            changed,
            RepresentationMode.MARKDOWN_TABLE,
            source_markdown=source,
        )

    assert exc.value.code == "NUMERIC_TOKEN_MISMATCH"


def test_numeric_validation_ignores_sentence_commas_after_amounts():
    source = "| 금액 |\n| --- |\n| 98,400원 |"
    structured = "# 금액\n- 98,400원,"

    assert validate_markdown_response(
        structured,
        RepresentationMode.STRUCTURED_MARKDOWN,
        source_markdown=source,
    ) == structured


def test_validate_markdown_table_allows_escaped_pipe_in_cell():
    source = "| 항목 | 설명 |\n| --- | --- |\n| 기본 | A\\|B |"
    assert validate_markdown_response(source, RepresentationMode.MARKDOWN_TABLE, source_markdown=source)


def test_validate_structured_markdown_requires_heading_and_bullet():
    assert validate_markdown_response(VALID_STRUCTURED, RepresentationMode.STRUCTURED_MARKDOWN, source_markdown=SOURCE_TABLE)
    with pytest.raises(TableResponseError):
        validate_markdown_response("10,000원", RepresentationMode.STRUCTURED_MARKDOWN, source_markdown=SOURCE_TABLE)


def test_service_retries_and_preserves_provider_json(tmp_path: Path):
    image = tmp_path / "table.png"
    image.write_bytes(b"png")
    first = {"id": "first", "choices": [{"message": {"content": "not markdown"}}]}
    second = {"id": "second", "choices": [{"message": {"content": VALID_TABLE}}]}
    fake = FakeClient([FakeResponse(first), FakeResponse(second)])
    result = TableReconstructionService(client=fake).reconstruct(
        table_id="page_0001_table_001",
        source_markdown=SOURCE_TABLE,
        image_path=image,
        representation_mode=RepresentationMode.MARKDOWN_TABLE,
    )
    assert result.final_status is ReconstructionStatus.SUCCEEDED
    assert result.selected_attempt == 2
    assert [a.outcome for a in result.attempts] == [AttemptOutcome.INVALID_RESPONSE, AttemptOutcome.SUCCEEDED]
    assert result.attempts[0].response == first
    assert result.attempts[1].response == second
    # base64 is sent to provider but never appears in the persisted result.
    assert "base64" not in json.dumps(result.as_dict(), ensure_ascii=False)
    assert len(fake.calls) == 2


def test_provider_response_redacts_echoed_image_data(tmp_path: Path):
    image = tmp_path / "table.png"
    image.write_bytes(b"png")
    provider = {
        "debug": "data:image/png;base64,c2VjcmV0",
        "choices": [{"message": {"content": VALID_TABLE}}],
    }
    result = TableReconstructionService(
        client=FakeClient([FakeResponse(provider)])
    ).reconstruct(
        table_id="t",
        source_markdown=SOURCE_TABLE,
        image_path=image,
        representation_mode=RepresentationMode.MARKDOWN_TABLE,
    )

    persisted = json.dumps(result.as_dict(), ensure_ascii=False)
    assert "c2VjcmV0" not in persisted
    assert "[REDACTED_IMAGE_DATA]" in persisted


def test_service_falls_back_after_two_invalid_attempts(tmp_path: Path):
    image = tmp_path / "table.png"
    image.write_bytes(b"png")
    payload = {"choices": [{"message": {"content": "bad"}}]}
    fake = FakeClient([FakeResponse(payload), FakeResponse(payload)])
    result = TableReconstructionService(client=fake).reconstruct(
        table_id="t",
        source_markdown=SOURCE_TABLE,
        image_path=image,
        representation_mode=RepresentationMode.MARKDOWN_TABLE,
    )
    assert result.final_status is ReconstructionStatus.FALLBACK
    assert result.final_markdown == SOURCE_TABLE
    assert len(result.attempts) == 2


def test_service_retries_truncated_response(tmp_path: Path):
    image = tmp_path / "table.png"
    image.write_bytes(b"png")
    truncated = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {"content": VALID_TABLE},
            }
        ]
    }
    completed = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": VALID_TABLE},
            }
        ]
    }
    result = TableReconstructionService(
        client=FakeClient([FakeResponse(truncated), FakeResponse(completed)])
    ).reconstruct(
        table_id="t",
        source_markdown=SOURCE_TABLE,
        image_path=image,
        representation_mode=RepresentationMode.MARKDOWN_TABLE,
    )

    assert result.final_status is ReconstructionStatus.SUCCEEDED
    assert result.selected_attempt == 2
    assert result.attempts[0].error == {
        "code": "TRUNCATED_RESPONSE",
        "message": "출력 토큰 제한으로 LLM 응답이 잘렸습니다",
    }


def test_missing_image_does_not_call_client(tmp_path: Path):
    fake = FakeClient([])
    result = TableReconstructionService(client=fake).reconstruct(
        table_id="t",
        source_markdown=SOURCE_TABLE,
        image_path=tmp_path / "missing.png",
        representation_mode=RepresentationMode.MARKDOWN_TABLE,
    )
    assert result.final_status is ReconstructionStatus.FALLBACK
    assert not fake.calls


def test_representation_mode_uses_three_simple_rules():
    assert (
        select_representation_mode([["a", "b"], ["c", "d"]], nested=False)
        is RepresentationMode.MARKDOWN_TABLE
    )
    assert (
        select_representation_mode([["a", "b"], ["c", "d"]], nested=True)
        is RepresentationMode.STRUCTURED_MARKDOWN
    )
    assert (
        select_representation_mode([["a", ""], ["c", "d"]], nested=False)
        is RepresentationMode.STRUCTURED_MARKDOWN
    )
    assert (
        select_representation_mode([["x" * 120, "b"]], nested=False)
        is RepresentationMode.STRUCTURED_MARKDOWN
    )
