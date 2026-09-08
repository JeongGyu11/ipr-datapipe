"""PDF Load의 PDF별 저장·독립 실행·페이지 상태 집계 테스트."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from app.application.pdf_load import PdfLoadApplication
from app.domain.pdf_load import (
    LoadTarget,
    LoadStatus,
    PageStatus,
    PreparedLoadItem,
    ParsedPage,
    ParsedTable,
    PdfLoadRequest,
    PdfParseOutput,
    RunStatus,
)
from app.infrastructure.artifacts import PdfLoadArtifactRepository


def _write_pdf_stub(path: Path, body: bytes = b"stub") -> Path:
    path.write_bytes(b"%PDF-1.7\n" + body)
    return path


class FakePdfParser:
    def __init__(
        self,
        *,
        page_statuses: tuple[PageStatus, ...] = (PageStatus.TEXT,),
        fail_name: str = "",
        warnings: list[dict[str, object]] | None = None,
    ) -> None:
        self.page_statuses = page_statuses
        self.fail_name = fail_name
        self.sources: list[Path] = []
        self.warnings = warnings or []

    def parse(self, source_pdf: Path, item_dir: Path) -> PdfParseOutput:
        self.sources.append(source_pdf)
        assert source_pdf.parent.name == "00_input"
        assert item_dir.name.startswith(".working_")
        if self.fail_name and source_pdf.name == self.fail_name:
            raise RuntimeError("의도한 파서 실패")

        table_md = item_dir / "02_tables" / "page_0001_table_001.md"
        table_xlsx = item_dir / "02_tables" / "page_0001_table_001.xlsx"
        processed_table_md = (
            item_dir / "03_processed" / "tables" / "page_0001_table_001.md"
        )
        table_md.write_text("| 항목 | 내용 |\n| --- | --- |", encoding="utf-8")
        table_xlsx.write_bytes(b"xlsx")
        processed_table_md.parent.mkdir(parents=True, exist_ok=True)
        processed_table_md.write_text(
            "| 항목 | 내용 |\n| --- | --- |", encoding="utf-8"
        )
        table = ParsedTable(
            table_id="page_0001_table_001",
            page_no=1,
            table_index=1,
            bbox=[1.0, 2.0, 3.0, 4.0],
            row_count=2,
            column_count=2,
            markdown_path="02_tables/page_0001_table_001.md",
            xlsx_path="02_tables/page_0001_table_001.xlsx",
            processed_markdown_path=(
                "03_processed/tables/page_0001_table_001.md"
            ),
            reconstruction={
                "status": "PASSTHROUGH_DISABLED",
                "representation_mode": None,
                "output_path": "03_processed/tables/page_0001_table_001.md",
                "response_path": None,
                "model": None,
                "prompt_version": None,
                "attempts": 0,
                "error_code": None,
            },
        )

        pages: list[ParsedPage] = []
        for page_no, status in enumerate(self.page_statuses, start=1):
            raw = "원문 헤더\n원문 본문" if status is PageStatus.TEXT else ""
            content = "정제 본문" if status is PageStatus.TEXT else ""
            markdown = f"{content}\n| 항목 | 값 |" if content else ""
            pages.append(
                ParsedPage(
                    page_no=page_no,
                    width=595.0,
                    height=842.0,
                    text_raw=raw,
                    text_content=content,
                    content_markdown=markdown,
                    meaningful_character_count=len(content),
                    word_count=len(content.split()),
                    image_count=1 if status is PageStatus.OCR_REQUIRED else 0,
                    largest_image_area_ratio=1.0 if status is PageStatus.OCR_REQUIRED else 0.0,
                    page_status=status,
                )
            )
        return PdfParseOutput(
            pages=pages,
            tables=[table],
            images=[],
            raw_text="\n\n---\n\n".join(page.text_raw for page in pages),
            content_markdown="\n\n---\n\n".join(page.content_markdown for page in pages),
            cropped_pdf_path=None,
            header_footer_analysis={"enabled": False, "applied": False},
            warnings=self.warnings,
        )


def _application(tmp_path: Path, parser: FakePdfParser) -> PdfLoadApplication:
    return PdfLoadApplication(
        artifact_repository=PdfLoadArtifactRepository(tmp_path / "load_test"),
        parser_factory=lambda: parser,
        header_footer_enabled=False,
    )


def test_prepare_item_writes_running_manifest_as_single_source_of_truth(
    tmp_path: Path,
) -> None:
    source = _write_pdf_stub(tmp_path / "준비.pdf")
    repository = PdfLoadArtifactRepository(tmp_path / "load_test")

    prepared = repository.prepare_item(
        LoadTarget(
            input_index=1,
            source_path=source,
            document_key="DOC_TEST",
            product_version_key="PROD_VER_TEST",
        )
    )

    manifest = json.loads(
        (prepared.item_dir / "99_result/load_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "RUNNING"
    assert manifest["completed_at"] is None
    assert manifest["summary"] == {}
    assert manifest["error"] is None
    assert manifest["source"]["sha256"] == prepared.sha256
    assert manifest["source"]["document_key"] == "DOC_TEST"
    assert manifest["source"]["product_version_key"] == "PROD_VER_TEST"
    assert manifest["artifacts"]["input_pdf"] == f"00_input/{source.name}"
    assert not (prepared.item_dir / "00_input/source_manifest.json").exists()
    assert not (prepared.item_dir / "01_extracted/document.json").exists()
    assert not (prepared.item_dir / "99_result/load_result.json").exists()


def test_load_writes_pdf_artifacts_directly_without_run_records(tmp_path: Path) -> None:
    source = _write_pdf_stub(tmp_path / "한글 보험약관.pdf")
    parser = FakePdfParser()
    result = _application(tmp_path, parser).run(PdfLoadRequest((source,)))

    assert result.status is RunStatus.SUCCEEDED
    assert result.items[0].status is LoadStatus.SUCCEEDED
    assert not hasattr(result.items[0], "chunk_count")
    assert parser.sources[0] != source
    item_dir = Path(result.items[0].item_dir or "")
    assert item_dir.parent == (tmp_path / "load_test").resolve()
    assert re.fullmatch(r"\d{8}_\d{6}_한글_보험약관", item_dir.name)
    assert {path.name for path in item_dir.iterdir()} == {
        "00_input",
        "02_images",
        "01_extracted",
        "02_tables",
        "03_processed",
        "90_debug",
        "99_result",
    }
    expected = [
        item_dir / "00_input" / source.name,
        item_dir / "01_extracted" / "pages.jsonl",
        item_dir / "01_extracted" / "raw_text.txt",
        item_dir / "01_extracted" / "pages" / "page_0001.txt",
        item_dir / "02_images" / "images.jsonl",
        item_dir / "02_tables" / "tables.jsonl",
        item_dir / "02_tables" / "page_0001_table_001.md",
        item_dir / "02_tables" / "page_0001_table_001.xlsx",
        item_dir / "03_processed" / "content.md",
        item_dir / "03_processed" / "pages.jsonl",
        item_dir / "03_processed" / "pages" / "page_0001.md",
        item_dir / "03_processed" / "tables" / "page_0001_table_001.md",
        item_dir / "90_debug" / "header_footer_analysis.json",
        item_dir / "99_result" / "load_manifest.json",
        item_dir / "99_result" / "warnings.jsonl",
    ]
    assert all(path.exists() for path in expected)
    processed_dir = item_dir / "03_processed"
    assert {path.name for path in processed_dir.iterdir()} == {
        "content.md",
        "pages.jsonl",
        "pages",
        "tables",
    }
    assert {path.name for path in (processed_dir / "pages").iterdir()} == {
        "page_0001.md"
    }
    assert (item_dir / "00_input" / source.name).read_bytes() == source.read_bytes()
    assert not (item_dir / "90_debug" / "cropped.pdf").exists()
    assert not any(
        (item_dir / legacy).exists()
        for legacy in ("input", "parsed", "chunks", "tables", "debug", "warnings")
    )
    assert not (item_dir / "source_manifest.json").exists()
    assert not (item_dir / "load_result.json").exists()
    assert not any(
        path.name
        in {
            "source_manifest.json",
            "document.json",
            "load_result.json",
            "tables_manifest.json",
            "images_manifest.json",
            "parse_warnings.json",
            "processed_pages.jsonl",
        }
        for path in item_dir.rglob("*")
    )
    forbidden = {"run_manifest.json", "summary.json", "errors.jsonl", "load.log"}
    assert not any(path.name in forbidden for path in (tmp_path / "load_test").rglob("*"))

    page = json.loads(
        (item_dir / "01_extracted" / "pages.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    processed_page = json.loads(
        (item_dir / "03_processed" / "pages.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert page["text_raw"] == "원문 헤더\n원문 본문"
    assert page["text_raw_path"] == "01_extracted/pages/page_0001.txt"
    assert (item_dir / page["text_raw_path"]).read_text(encoding="utf-8") == page["text_raw"]
    assert "text_content" not in page
    assert "content_markdown" not in page
    assert "table_refs" not in page
    assert "image_refs" not in page
    assert "text_raw" not in processed_page
    assert processed_page["text_content"] == "정제 본문"
    assert processed_page["content_markdown"].endswith("| 항목 | 값 |")
    assert processed_page["content_markdown_path"] == "03_processed/pages/page_0001.md"
    assert "text_content_path" not in processed_page
    assert (
        (item_dir / processed_page["content_markdown_path"]).read_text(encoding="utf-8")
        == processed_page["content_markdown"]
    )
    assert not (item_dir / "03_processed" / "chunks.jsonl").exists()
    assert not list((item_dir / "03_processed" / "pages").glob("*.txt"))

    manifest = json.loads(
        (item_dir / "99_result" / "load_manifest.json").read_text(encoding="utf-8")
    )
    table_rows = [
        json.loads(line)
        for line in (item_dir / "02_tables" / "tables.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    image_rows = (item_dir / "02_images" / "images.jsonl").read_text(encoding="utf-8")
    assert manifest["schema_version"] == "pdf-load-v6"
    assert manifest["versions"] == {
        "loader": "pdf-loader-v6",
        "parser": "prosure-pdf2md-v6",
    }
    assert manifest["status"] == "SUCCEEDED"
    assert manifest["completed_at"]
    assert manifest["error"] is None
    assert manifest["source"]["copied_path"] == f"00_input/{source.name}"
    assert "document_key" not in manifest["source"]
    assert "product_version_key" not in manifest["source"]
    assert manifest["summary"]["page_count"] == 1
    assert manifest["summary"]["table_count"] == 1
    assert manifest["summary"]["detected_table_count"] == 1
    assert manifest["summary"]["fragment_table_count"] == 0
    assert manifest["summary"]["rejected_table_count"] == 0
    assert manifest["summary"]["image_count"] == 0
    assert manifest["summary"]["table_reconstruction"] == {
        "enabled": False,
        "eligible_count": 1,
        "succeeded_count": 0,
        "fallback_count": 0,
        "passthrough_count": 1,
        "skipped_count": 0,
    }
    assert manifest["artifacts"]["raw_pages"] == "01_extracted/pages.jsonl"
    assert manifest["artifacts"]["processed_pages"] == "03_processed/pages.jsonl"
    assert manifest["artifacts"]["processed_tables_dir"] == "03_processed/tables"
    assert manifest["artifacts"]["tables"] == "02_tables/tables.jsonl"
    assert manifest["artifacts"]["images"] == "02_images/images.jsonl"
    assert manifest["artifacts"]["warnings"] == "99_result/warnings.jsonl"
    assert image_rows == ""
    assert "chunk_count" not in manifest["summary"]
    assert "chunks" not in manifest["artifacts"]
    assert "chunks" not in PdfParseOutput.__dataclass_fields__
    assert "chunk_count" not in type(result.items[0]).__dataclass_fields__
    assert table_rows[0]["files"]["markdown"].startswith("02_tables/")
    assert "page_width" not in table_rows[0]
    assert "page_height" not in table_rows[0]
    assert table_rows[0]["reconstruction"]["status"] == "PASSTHROUGH_DISABLED"
    assert table_rows[0]["files"]["processed_markdown"].startswith(
        "03_processed/tables/"
    )
    assert table_rows[0]["quality_status"] == "MEANINGFUL"
    assert table_rows[0]["quality_reason"] == "STRUCTURED_TABLE"


def test_load_item_uses_artifact_id_as_trace_context(tmp_path: Path, monkeypatch) -> None:
    source = _write_pdf_stub(tmp_path / "추적.pdf")
    pushed: list[str] = []
    reset: list[object] = []
    token = object()
    monkeypatch.setattr(
        "app.application.pdf_load.push_trace_id",
        lambda value: pushed.append(value) or token,
    )
    monkeypatch.setattr(
        "app.application.pdf_load.reset_trace_id",
        lambda value: reset.append(value),
    )

    result = _application(tmp_path, FakePdfParser()).run(PdfLoadRequest((source,)))

    assert result.items[0].status is LoadStatus.SUCCEEDED
    assert pushed == [Path(result.items[0].item_dir or "").name]
    assert reset == [token]


def test_final_folder_name_uses_second_and_pdf_stem_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    source = _write_pdf_stub(tmp_path / "1000386 교보연금 통합약관.pdf")
    monkeypatch.setattr(
        "app.infrastructure.artifacts.pdf_load_repository._now",
        lambda: datetime(2026, 9, 2, 15, 35, 41, 852060, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    result = _application(tmp_path, FakePdfParser()).run(PdfLoadRequest((source,)))

    item_dir = Path(result.items[0].item_dir or "")
    assert item_dir.name == "20260902_153541_1000386_교보연금_통합약관"
    assert "PDF_" not in item_dir.name
    assert "852060" not in item_dir.name
    assert result.items[0].sha256 not in item_dir.name


def test_existing_final_folder_is_not_overwritten(tmp_path: Path, monkeypatch) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    source = _write_pdf_stub(tmp_path / "약관.pdf")
    monkeypatch.setattr(
        "app.infrastructure.artifacts.pdf_load_repository._now",
        lambda: datetime(2026, 9, 2, 15, 35, 41, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    existing = tmp_path / "load_test" / "20260902_153541_약관"
    existing.mkdir(parents=True)

    result = _application(tmp_path, FakePdfParser()).run(PdfLoadRequest((source,)))

    assert result.items[0].status is LoadStatus.FAILED
    assert result.items[0].error_stage == "COPY_INPUT"
    assert result.items[0].error_code == "FileExistsError"
    assert result.items[0].item_dir is None
    assert not list((tmp_path / "load_test").glob(".working_*"))


def test_finalize_retries_transient_windows_access_denial_and_keeps_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _write_pdf_stub(tmp_path / "rename-retry.pdf")
    repository = PdfLoadArtifactRepository(tmp_path / "load_test")
    application = PdfLoadApplication(
        artifact_repository=repository,
        parser_factory=FakePdfParser,
        header_footer_enabled=False,
    )
    original_rename = Path.rename
    rename_attempts = 0

    def flaky_rename(path: Path, target: Path) -> Path:
        nonlocal rename_attempts
        if path.name.startswith(".working_"):
            rename_attempts += 1
            if rename_attempts <= 4:
                raise PermissionError(13, "일시적인 Windows 접근 거부", str(path))
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", flaky_rename)
    monkeypatch.setattr(
        "app.infrastructure.artifacts.pdf_load_repository.time.sleep",
        lambda _seconds: None,
    )

    result = application.run(PdfLoadRequest((source,)))

    assert rename_attempts == 5
    assert result.items[0].status is LoadStatus.SUCCEEDED
    assert Path(result.items[0].item_dir or "").is_dir()


def test_finalize_accepts_move_completed_before_permission_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _write_pdf_stub(tmp_path / "rename-ambiguous.pdf")
    application = _application(tmp_path, FakePdfParser())
    original_rename = Path.rename

    def moved_then_failed(path: Path, target: Path) -> Path:
        moved = original_rename(path, target)
        if path.name.startswith(".working_"):
            raise PermissionError(13, "이동 완료 후 보고된 접근 거부", str(path))
        return moved

    monkeypatch.setattr(Path, "rename", moved_then_failed)

    result = application.run(PdfLoadRequest((source,)))

    assert result.items[0].status is LoadStatus.SUCCEEDED
    assert Path(result.items[0].item_dir or "").is_dir()
    assert not list((tmp_path / "load_test").glob(".working_*"))


def test_finalize_rejects_conflicting_or_missing_directory_states(tmp_path: Path) -> None:
    repository = PdfLoadArtifactRepository(tmp_path / "load_test")
    source = _write_pdf_stub(tmp_path / "state-check.pdf")
    target = LoadTarget(input_index=1, source_path=source)
    staging = tmp_path / ".working_state"
    final = tmp_path / "PDF_state"
    copied = staging / "00_input" / source.name
    prepared = PreparedLoadItem(
        target=target,
        item_dir=staging,
        final_item_dir=final,
        copied_pdf_path=copied,
        sha256="0" * 64,
        size_bytes=source.stat().st_size,
    )

    staging.mkdir()
    final.mkdir()
    with pytest.raises(FileExistsError):
        repository.finalize_item(prepared)

    shutil.rmtree(staging)
    shutil.rmtree(final)
    with pytest.raises(FileNotFoundError):
        repository.finalize_item(prepared)


def test_finalize_permanent_access_denial_fails_after_exactly_five_attempts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _write_pdf_stub(tmp_path / "rename-permanent-failure.pdf")
    application = _application(tmp_path, FakePdfParser())
    rename_attempts = 0

    def denied_rename(path: Path, target: Path) -> Path:
        nonlocal rename_attempts
        if path.name.startswith(".working_"):
            rename_attempts += 1
            raise PermissionError(13, "영구적인 Windows 접근 거부", str(path))
        raise AssertionError(f"예상하지 않은 rename: {path} -> {target}")

    monkeypatch.setattr(Path, "rename", denied_rename)
    monkeypatch.setattr(
        "app.infrastructure.artifacts.pdf_load_repository.time.sleep",
        lambda _seconds: None,
    )

    result = application.run(PdfLoadRequest((source,)))

    item = result.items[0]
    assert rename_attempts == 5
    assert item.status is LoadStatus.FAILED
    assert item.error_stage == "FINALIZE_ARTIFACTS"
    assert item.error_code == "PermissionError"
    assert Path(item.item_dir or "").name.startswith(".working_")
    saved = json.loads(
        (Path(item.item_dir or "") / "99_result" / "load_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved["status"] == "FAILED"
    assert saved["error"]["stage"] == "FINALIZE_ARTIFACTS"


def test_multiple_pdfs_are_independent_and_failure_is_published_per_item(tmp_path: Path) -> None:
    first = _write_pdf_stub(tmp_path / "실패.pdf", b"first")
    second = _write_pdf_stub(tmp_path / "성공.pdf", b"second")
    parser = FakePdfParser(fail_name=first.name)

    result = _application(tmp_path, parser).run(PdfLoadRequest((first, second)))

    assert result.status is RunStatus.PARTIAL
    assert [item.status for item in result.items] == [LoadStatus.FAILED, LoadStatus.SUCCEEDED]
    assert [source.name for source in parser.sources] == [first.name, second.name]
    failed_result = json.loads(
        (Path(result.items[0].item_dir or "") / "99_result" / "load_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert failed_result["status"] == "FAILED"
    assert failed_result["error"]["stage"] == "PARSE_PDF"


def test_page_file_write_failure_is_recorded_as_save_artifacts_failure(tmp_path: Path) -> None:
    class FailingPageArtifactRepository(PdfLoadArtifactRepository):
        @staticmethod
        def write_text(path: Path, content: str) -> None:
            if path.as_posix().endswith("03_processed/pages/page_0001.md"):
                raise OSError("의도한 페이지 파일 저장 실패")
            PdfLoadArtifactRepository.write_text(path, content)

    source = _write_pdf_stub(tmp_path / "페이지저장실패.pdf")
    application = PdfLoadApplication(
        artifact_repository=FailingPageArtifactRepository(tmp_path / "load_test"),
        parser_factory=FakePdfParser,
        header_footer_enabled=False,
    )

    result = application.run(PdfLoadRequest((source,)))

    item = result.items[0]
    assert item.status is LoadStatus.FAILED
    assert item.error_stage == "SAVE_ARTIFACTS"
    item_dir = Path(item.item_dir or "")
    saved_result = json.loads(
        (item_dir / "99_result" / "load_manifest.json").read_text(encoding="utf-8")
    )
    assert saved_result["status"] == "FAILED"
    assert saved_result["error"]["stage"] == "SAVE_ARTIFACTS"
    assert saved_result["error"]["code"] == "OSError"


def test_parser_factory_is_called_for_each_pdf(tmp_path: Path) -> None:
    first = _write_pdf_stub(tmp_path / "첫번째.pdf", b"first")
    second = _write_pdf_stub(tmp_path / "두번째.pdf", b"second")
    parsers: list[FakePdfParser] = []

    def factory() -> FakePdfParser:
        parser = FakePdfParser()
        parsers.append(parser)
        return parser

    application = PdfLoadApplication(
        artifact_repository=PdfLoadArtifactRepository(tmp_path / "load_test"),
        parser_factory=factory,
        header_footer_enabled=False,
    )
    result = application.run(PdfLoadRequest((first, second)))

    assert result.status is RunStatus.SUCCEEDED
    assert len(parsers) == 2
    assert [len(parser.sources) for parser in parsers] == [1, 1]


def test_parser_initialization_failure_is_isolated_per_pdf(tmp_path: Path) -> None:
    first = _write_pdf_stub(tmp_path / "초기화실패.pdf", b"first")
    second = _write_pdf_stub(tmp_path / "정상.pdf", b"second")
    calls = 0

    def factory() -> FakePdfParser:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("파서 초기화 실패")
        return FakePdfParser()

    application = PdfLoadApplication(
        artifact_repository=PdfLoadArtifactRepository(tmp_path / "load_test"),
        parser_factory=factory,
        header_footer_enabled=False,
    )
    result = application.run(PdfLoadRequest((first, second)))

    assert [item.status for item in result.items] == [LoadStatus.FAILED, LoadStatus.SUCCEEDED]
    assert result.items[0].error_stage == "INITIALIZE_PARSER"


def test_page_level_ocr_statuses_are_aggregated(tmp_path: Path) -> None:
    source = _write_pdf_stub(tmp_path / "혼합.pdf")
    parser = FakePdfParser(page_statuses=(PageStatus.TEXT, PageStatus.OCR_REQUIRED, PageStatus.EMPTY))

    result = _application(tmp_path, parser).run(PdfLoadRequest((source,)))

    item = result.items[0]
    assert item.status is LoadStatus.PARTIAL
    assert item.ocr_required_pages == [2]
    assert item.empty_pages == [3]
    assert item.page_status_counts == {"TEXT": 1, "OCR_REQUIRED": 1, "EMPTY": 1}

    item_dir = Path(item.item_dir or "")
    raw_rows = [
        json.loads(line)
        for line in (item_dir / "01_extracted" / "pages.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    processed_rows = [
        json.loads(line)
        for line in (item_dir / "03_processed" / "pages.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(raw_rows) == len(parser.page_statuses) == 3
    assert len(processed_rows) == len(raw_rows)
    assert [row["page_no"] for row in raw_rows] == [1, 2, 3]
    assert [row["page_no"] for row in processed_rows] == [1, 2, 3]
    for raw_row, processed_row in zip(raw_rows, processed_rows, strict=True):
        raw_path = raw_row["text_raw_path"]
        markdown_path = processed_row["content_markdown_path"]
        assert "\\" not in raw_path
        assert "\\" not in markdown_path
        assert (item_dir / raw_path).read_text(encoding="utf-8") == raw_row["text_raw"]
        assert (
            (item_dir / markdown_path).read_text(encoding="utf-8")
            == processed_row["content_markdown"]
        )

    # OCR_REQUIRED·EMPTY 페이지도 누락하지 않고 페이지 파일을 생성한다.
    assert (item_dir / "01_extracted" / "pages" / "page_0002.txt").exists()
    assert (item_dir / "01_extracted" / "pages" / "page_0003.txt").exists()
    assert (item_dir / "03_processed" / "pages" / "page_0002.md").exists()
    assert (item_dir / "03_processed" / "pages" / "page_0003.md").exists()
    assert not list((item_dir / "03_processed" / "pages").glob("*.txt"))
    assert (item_dir / "01_extracted" / "pages" / "page_0002.txt").read_text(encoding="utf-8") == ""
    assert (item_dir / "03_processed" / "pages" / "page_0003.md").read_text(encoding="utf-8") == ""


def test_document_without_usable_text_is_ocr_required(tmp_path: Path) -> None:
    source = _write_pdf_stub(tmp_path / "스캔.pdf")
    result = _application(
        tmp_path,
        FakePdfParser(page_statuses=(PageStatus.OCR_REQUIRED, PageStatus.EMPTY)),
    ).run(PdfLoadRequest((source,)))

    assert result.status is RunStatus.PARTIAL
    assert result.items[0].status is LoadStatus.OCR_REQUIRED


@pytest.mark.parametrize(
    "warning_code",
    [
        "TABLE_DETECTION_FAILED",
        "TABLE_EXTRACTION_FAILED",
        "IMAGE_EXTRACTION_UNAVAILABLE",
        "IMAGE_DETECTION_FAILED",
        "IMAGE_EXTRACTION_FAILED",
        "TABLE_RECONSTRUCTION_FALLBACK",
    ],
)
def test_core_extraction_warning_lowers_text_document_to_partial(
    tmp_path: Path,
    warning_code: str,
) -> None:
    source = _write_pdf_stub(tmp_path / f"{warning_code}.pdf")
    parser = FakePdfParser(warnings=[{"code": warning_code, "page_no": 1}])

    result = _application(tmp_path, parser).run(PdfLoadRequest((source,)))

    assert result.items[0].status is LoadStatus.PARTIAL


@pytest.mark.parametrize(
    "warning_code",
    [
        "TABLE_RENDER_FAILED",
        "CROPPED_PDF_FAILED",
        "CROPPED_PDF_UNAVAILABLE",
        "TABLE_ILLEGAL_CONTROL_CHARACTERS_REMOVED",
    ],
)
def test_non_core_warning_does_not_lower_success_status(
    tmp_path: Path,
    warning_code: str,
) -> None:
    source = _write_pdf_stub(tmp_path / f"{warning_code}.pdf")
    parser = FakePdfParser(warnings=[{"code": warning_code, "page_no": 1}])

    result = _application(tmp_path, parser).run(PdfLoadRequest((source,)))

    assert result.items[0].status is LoadStatus.SUCCEEDED


def test_ocr_required_has_priority_over_core_extraction_warning(tmp_path: Path) -> None:
    source = _write_pdf_stub(tmp_path / "스캔_추출경고.pdf")
    parser = FakePdfParser(
        page_statuses=(PageStatus.OCR_REQUIRED,),
        warnings=[
            {
                "code": "TABLE_DETECTION_FAILED",
                "page_no": 1,
                "message": "details",
            }
        ],
    )

    result = _application(tmp_path, parser).run(PdfLoadRequest((source,)))

    assert result.items[0].status is LoadStatus.OCR_REQUIRED


def test_dynamic_warning_code_is_not_treated_as_core_warning(tmp_path: Path) -> None:
    """Warning details must not be encoded into the machine-readable code."""

    source = _write_pdf_stub(tmp_path / "legacy-warning.pdf")
    parser = FakePdfParser(
        warnings=[{"code": "TABLE_EXTRACTION_FAILED:1:details", "page_no": 1}]
    )

    result = _application(tmp_path, parser).run(PdfLoadRequest((source,)))

    assert result.items[0].status is LoadStatus.SUCCEEDED


def test_invalid_input_leaves_no_artifact_and_does_not_stop_valid_pdf(tmp_path: Path) -> None:
    missing = tmp_path / "없음.pdf"
    valid = _write_pdf_stub(tmp_path / "정상.pdf")
    result = _application(tmp_path, FakePdfParser()).run(PdfLoadRequest((missing, valid)))

    assert result.status is RunStatus.PARTIAL
    assert result.items[0].error_code == "PDF_NOT_FOUND"
    assert result.items[0].item_dir is None
    assert result.items[1].status is LoadStatus.SUCCEEDED
    published = [
        path
        for path in (tmp_path / "load_test").iterdir()
        if path.is_dir() and not path.name.startswith(".working_")
    ]
    assert len(published) == 1
