from __future__ import annotations

import json
from pathlib import Path

import app.infrastructure.pdf.prosure.parser as parser_module
from app.infrastructure.llm import TableReconstructionService
from app.infrastructure.pdf.prosure.parser import ProSurePdfParser


class FakeResponse:
    def __init__(self, content: str):
        self.status_code = 200
        self._payload = {"id": content.splitlines()[0], "choices": [{"message": {"content": content}}]}

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    def post(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class FakeTable:
    def __init__(self, bbox, rows):
        self.bbox = bbox
        self._rows = rows

    def extract(self):
        return self._rows


class FakePage:
    width = 300
    height = 300
    images: list[dict[str, object]] = []

    def __init__(self, tables):
        self._tables = tables

    def extract_text(self):
        return "페이지 본문"

    def extract_words(self):
        return [
            {"text": "페이지", "x0": 220, "x1": 250, "top": 220, "bottom": 230},
            {"text": "본문", "x0": 255, "x1": 280, "top": 220, "bottom": 230},
        ]

    def find_tables(self):
        return self._tables


class FakePdf:
    def __init__(self, tables):
        self.pages = [FakePage(tables)]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class FakePdfPlumber:
    def __init__(self, tables):
        self.tables = tables

    def open(self, _path):
        return FakePdf(self.tables)


class FakeRenderer:
    def __init__(self, _source_pdf):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def render(self, *, output_path: Path, **_kwargs):
        output_path.write_bytes(b"png")


def _install_pdf_fakes(monkeypatch, tables):
    monkeypatch.setattr(parser_module, "_require_pdfplumber", lambda: FakePdfPlumber(tables))
    monkeypatch.setattr(parser_module, "TableRegionRenderer", FakeRenderer)
    monkeypatch.setattr(
        parser_module,
        "extract_embedded_images",
        lambda _source_pdf, _output_dir: ([], {}, []),
    )


def test_nested_tables_are_called_sequentially_but_only_outer_is_rendered(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    tables = [
        FakeTable((10, 10, 200, 200), [["항목", "금액"], ["바깥", "10원"]]),
        FakeTable((100, 50, 190, 120), [["항목", "금액"], ["안쪽", "20원"]]),
    ]
    _install_pdf_fakes(monkeypatch, tables)
    client = FakeClient(
        [
            FakeResponse("# 바깥\n- 항목\n  - 금액: 10원"),
            FakeResponse("# 안쪽\n- 항목\n  - 금액: 20원"),
        ]
    )
    service = TableReconstructionService(client=client)

    output = ProSurePdfParser(table_reconstructor=service).parse(
        source, tmp_path / "item"
    )

    assert len(client.calls) == 2
    assert all(
        call[1]["json"]["messages"][1]["content"][1]["type"] == "image_url"
        for call in client.calls
    )
    outer, inner = output.tables
    assert outer.contained_by is None
    assert outer.included_in_page is True
    assert inner.contained_by == outer.table_id
    assert inner.included_in_page is False
    assert outer.reconstruction["representation_mode"] == "STRUCTURED_MARKDOWN"
    assert inner.reconstruction["representation_mode"] == "STRUCTURED_MARKDOWN"
    assert "# 바깥\n" in output.pages[0].content_markdown
    assert "# 안쪽\n" not in output.pages[0].content_markdown

    for table in output.tables:
        processed = tmp_path / "item" / table.processed_markdown_path
        response_path = tmp_path / "item" / table.reconstruction["response_path"]
        assert processed.is_file()
        response = json.loads(response_path.read_text(encoding="utf-8"))
        assert len(response["attempts"]) == 1
        assert response["attempts"][0]["response"]["choices"]
        assert "base64" not in response_path.read_text(encoding="utf-8")


def test_failed_reconstruction_records_both_responses_and_falls_back(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    tables = [FakeTable((10, 10, 200, 100), [["항목", "금액"], ["기본", "10원"]])]
    _install_pdf_fakes(monkeypatch, tables)
    client = FakeClient([FakeResponse("잘못된 응답"), FakeResponse("다시 잘못된 응답")])

    output = ProSurePdfParser(
        table_reconstructor=TableReconstructionService(client=client)
    ).parse(source, tmp_path / "item")

    table = output.tables[0]
    assert table.reconstruction["status"] == "FALLBACK"
    assert table.reconstruction["attempts"] == 2
    assert any(
        warning["code"] == "TABLE_RECONSTRUCTION_FALLBACK"
        for warning in output.warnings
    )
    response = json.loads(
        (tmp_path / "item" / table.reconstruction["response_path"]).read_text(
            encoding="utf-8"
        )
    )
    assert [attempt["outcome"] for attempt in response["attempts"]] == [
        "INVALID_RESPONSE",
        "INVALID_RESPONSE",
    ]
    assert (
        tmp_path / "item" / table.processed_markdown_path
    ).read_text(encoding="utf-8") == (
        tmp_path / "item" / table.markdown_path
    ).read_text(encoding="utf-8")


def test_disabled_reconstruction_writes_passthrough_processed_table(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    tables = [FakeTable((10, 10, 200, 100), [["항목", "금액"], ["기본", "10원"]])]
    _install_pdf_fakes(monkeypatch, tables)

    output = ProSurePdfParser().parse(source, tmp_path / "item")

    table = output.tables[0]
    assert table.reconstruction["status"] == "PASSTHROUGH_DISABLED"
    assert table.reconstruction["response_path"] is None
    assert output.table_reconstruction_enabled is False
    assert (
        tmp_path / "item" / table.processed_markdown_path
    ).read_text(encoding="utf-8") == (
        tmp_path / "item" / table.markdown_path
    ).read_text(encoding="utf-8")
