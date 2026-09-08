"""PDF Load v5 이미지·표 PNG 산출물 계약 테스트."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf

from app.application.pdf_load import PdfLoadApplication
from app.domain.pdf_load import PdfLoadRequest, RunStatus
from app.infrastructure.artifacts import PdfLoadArtifactRepository
from app.infrastructure.pdf.prosure.images import TableRegionRenderer


def _solid_png(*, width: int, height: int, color: int) -> bytes:
    pixmap = pymupdf.Pixmap(
        pymupdf.csRGB,
        pymupdf.IRect(0, 0, width, height),
        False,
    )
    pixmap.clear_with(color)
    try:
        return pixmap.tobytes("png")
    finally:
        pixmap = None


def _write_embedded_image_pdf(path: Path) -> tuple[bytes, bytes, bytes]:
    """두 페이지에서 이미지 중복·장식 필터와 위치순 참조를 검증할 fixture."""

    repeated_png = _solid_png(width=96, height=72, color=0x3366CC)
    second_png = _solid_png(width=96, height=72, color=0xCC6633)
    decorative_png = _solid_png(width=2, height=2, color=0x00FF00)

    document = pymupdf.open()
    try:
        first = document.new_page(width=600, height=800)
        first.insert_text((72, 60), "상품 보장 안내 페이지 1")
        # Insert the lower image first in the content stream.  Extraction must
        # still expose occurrences in visual (top/left) order.
        first.insert_image(pymupdf.Rect(72, 500, 272, 640), stream=second_png)
        first.insert_text((72, 330), "이미지 사이의 본문")
        first.insert_image(pymupdf.Rect(72, 110, 272, 250), stream=repeated_png)
        first.insert_image(pymupdf.Rect(4, 4, 6, 6), stream=decorative_png)

        second = document.new_page(width=600, height=800)
        second.insert_text((72, 60), "상품 보장 안내 페이지 2")
        second.insert_image(pymupdf.Rect(72, 110, 272, 250), stream=repeated_png)
        second.insert_image(pymupdf.Rect(4, 4, 6, 6), stream=decorative_png)
        document.save(path)
    finally:
        document.close()
    return repeated_png, second_png, decorative_png


def _write_nested_table_pdf(path: Path) -> None:
    """외부 표의 셀 안에 하위 표를 그린 PyMuPDF fixture."""

    document = pymupdf.open()
    try:
        page = document.new_page(width=600, height=760)
        # ROOT 표: 3열·4행.
        for x in (50, 170, 400, 550):
            page.draw_line((x, 100), (x, 500), width=1)
        for y in (100, 200, 300, 400, 500):
            page.draw_line((50, y), (550, y), width=1)
        page.insert_text((72, 150), "급부명")
        page.insert_text((230, 150), "지급사유")
        page.insert_text((430, 150), "지급금액")
        page.insert_text((72, 250), "영구치 보존치료비")
        page.insert_text((230, 250), "치료를 받은 경우")

        # 지급금액 셀 안의 NESTED 표.
        for x in (420, 475, 530):
            page.draw_line((x, 220), (x, 360), width=1)
        for y in (220, 255, 290, 325, 360):
            page.draw_line((420, y), (530, y), width=1)
        page.insert_text((425, 245), "보존치료")
        page.insert_text((480, 245), "지급금액")
        page.insert_text((425, 280), "아말감")
        page.insert_text((480, 280), "1만원")
        page.insert_text((425, 315), "크라운")
        page.insert_text((480, 315), "20만원")

        # 같은 페이지의 단순 표: 모든 표를 PNG로 만들지 않는지 비교한다.
        for x in (60, 180, 300):
            page.draw_line((x, 560), (x, 650), width=1)
        for y in (560, 605, 650):
            page.draw_line((60, y), (300, y), width=1)
        page.insert_text((70, 590), "항목")
        page.insert_text((190, 590), "값")
        page.insert_text((70, 635), "기본")
        page.insert_text((190, 635), "적용")
        document.save(path)
    finally:
        document.close()


def _run_default_load(tmp_path: Path, source: Path):
    repository = PdfLoadArtifactRepository(tmp_path / "load_test")
    application = PdfLoadApplication(artifact_repository=repository, header_footer_enabled=False)
    result = application.run(PdfLoadRequest((source,)))
    assert result.status is RunStatus.SUCCEEDED
    return result, Path(result.items[0].item_dir or "")


def test_embedded_images_are_saved_deduplicated_and_referenced_in_order(tmp_path: Path) -> None:
    source = tmp_path / "이미지상품요약서.pdf"
    repeated_png, second_png, decorative_png = _write_embedded_image_pdf(source)
    _, item_dir = _run_default_load(tmp_path, source)

    images_dir = item_dir / "02_images"
    records = [
        json.loads(line)
        for line in (images_dir / "images.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    # 장식성 2x2 이미지는 제외되고, 서로 다른 바이트의 이미지만 물리 저장된다.
    assert len(records) == 2
    assert all(record["extraction_mode"] == "EMBEDDED" for record in records)
    assert {record["sha256"] for record in records} == {
        hashlib.sha256(repeated_png).hexdigest(),
        hashlib.sha256(second_png).hexdigest(),
    }
    assert hashlib.sha256(decorative_png).hexdigest() not in {
        record["sha256"] for record in records
    }

    repeated = next(record for record in records if record["sha256"] == hashlib.sha256(repeated_png).hexdigest())
    second = next(record for record in records if record["sha256"] == hashlib.sha256(second_png).hexdigest())
    assert len(repeated["occurrences"]) == 2
    assert len(second["occurrences"]) == 1
    for record in records:
        image_path = item_dir / record["image_path"]
        assert image_path.exists()
        assert image_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".jp2"}
        assert image_path.read_bytes() in {repeated_png, second_png}

    raw_rows = [
        json.loads(line)
        for line in (item_dir / "01_extracted" / "pages.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert all("image_refs" not in row for row in raw_rows)
    assert all("table_refs" not in row for row in raw_rows)
    processed_rows = [
        json.loads(line)
        for line in (item_dir / "03_processed" / "pages.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert processed_rows[0]["image_refs"] == [repeated["image_id"], second["image_id"]]
    assert processed_rows[1]["image_refs"] == [repeated["image_id"]]

    page_markdown = (item_dir / "03_processed/pages/page_0001.md").read_text(encoding="utf-8")
    first_name = Path(repeated["image_path"]).name
    second_name = Path(second["image_path"]).name
    assert first_name in page_markdown and second_name in page_markdown
    assert page_markdown.index(first_name) < page_markdown.index(second_name)

    load_manifest = json.loads(
        (item_dir / "99_result/load_manifest.json").read_text(encoding="utf-8")
    )
    assert load_manifest["summary"]["image_count"] == 2
    assert load_manifest["summary"]["image_occurrence_count"] == 3
    assert load_manifest["summary"]["table_image_count"] == 0
    assert load_manifest["artifacts"]["images"] == "02_images/images.jsonl"


def test_every_extracted_table_has_matching_rendered_png(tmp_path: Path) -> None:
    source = tmp_path / "중첩표상품요약서.pdf"
    _write_nested_table_pdf(source)
    _, item_dir = _run_default_load(tmp_path, source)

    tables = [
        json.loads(line)
        for line in (item_dir / "02_tables" / "tables.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    rendered = [table for table in tables if table["files"].get("png")]
    assert tables, "표가 한 개 이상 추출되어야 한다"
    assert len(rendered) == len(tables), "추출된 모든 표에 PNG 캡처가 있어야 한다"
    for table in rendered:
        rendered_path = item_dir / table["files"]["png"]
        assert rendered_path.suffix.lower() == ".png"
        assert rendered_path.stem == Path(table["files"]["markdown"]).stem
        assert rendered_path.stem == Path(table["files"]["xlsx"]).stem
        assert rendered_path.exists()
        assert rendered_path.stat().st_size > 0
        pixmap = pymupdf.Pixmap(rendered_path)
        bbox = table["bbox"]
        assert pixmap.width > (bbox[2] - bbox[0]) * 2
        assert pixmap.height > (bbox[3] - bbox[1]) * 2
    load_manifest = json.loads(
        (item_dir / "99_result/load_manifest.json").read_text(encoding="utf-8")
    )
    assert load_manifest["summary"]["table_image_count"] == len(rendered)


def test_table_renderer_reuses_one_open_document_for_multiple_tables(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "renderer.pdf"
    _write_nested_table_pdf(source)
    first_output = tmp_path / "first.png"
    second_output = tmp_path / "second.png"

    real_open = pymupdf.open
    open_calls = 0

    def counting_open(*args, **kwargs):
        nonlocal open_calls
        open_calls += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(pymupdf, "open", counting_open)
    with TableRegionRenderer(source) as renderer:
        renderer.render(1, [50, 100, 550, 500], first_output)
        renderer.render(1, [60, 560, 300, 650], second_output)

    assert open_calls == 1
    assert first_output.exists() and first_output.stat().st_size > 0
    assert second_output.exists() and second_output.stat().st_size > 0


def test_parser_opens_one_table_renderer_for_all_extracted_tables(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "parser-renderer.pdf"
    _write_nested_table_pdf(source)
    real_enter = TableRegionRenderer.__enter__
    enter_calls = 0

    def counting_enter(renderer: TableRegionRenderer) -> TableRegionRenderer:
        nonlocal enter_calls
        enter_calls += 1
        return real_enter(renderer)

    monkeypatch.setattr(TableRegionRenderer, "__enter__", counting_enter)

    _, item_dir = _run_default_load(tmp_path, source)
    tables = [
        json.loads(line)
        for line in (item_dir / "02_tables" / "tables.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert len(tables) > 1
    assert enter_calls == 1
