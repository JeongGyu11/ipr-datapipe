"""파일 기반 PDF Load 산출물 저장소."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from app.config_paths import PROJECT_ROOT
from app.domain.pdf_load import (
    LOADER_VERSION,
    LOAD_SCHEMA_VERSION,
    PARSER_VERSION,
    LoadTarget,
    PdfParseOutput,
    PreparedLoadItem,
)
from crawler.validators import validate_saved_file
from utils.file_utils import normalize_storage_component

KST = ZoneInfo("Asia/Seoul")
_COPY_CHUNK_SIZE = 1024 * 1024
_FINALIZE_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8)
_WINDOWS_RETRYABLE_RENAME_ERRORS = {5, 32}


def _now() -> datetime:
    return datetime.now(KST)


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    value_attr = getattr(value, "value", None)
    if value_attr is not None:
        return value_attr
    raise TypeError(f"JSON으로 변환할 수 없습니다: {type(value).__name__}")


class PdfLoadArtifactRepository:
    def __init__(self, output_root: Path | None = None):
        self.output_root = (output_root or PROJECT_ROOT / "artifacts" / "load_test").resolve()

    def prepare_item(self, target: LoadTarget) -> PreparedLoadItem:
        self.output_root.mkdir(parents=True, exist_ok=True)
        created_at = _now()
        stem = normalize_storage_component(target.source_path.stem, max_length=64)
        artifact_id = f"{created_at:%Y%m%d_%H%M%S}_{stem}"
        final_item_dir = self.output_root / artifact_id
        if final_item_dir.exists():
            raise FileExistsError(f"같은 시각과 PDF명의 결과 폴더가 이미 존재합니다: {final_item_dir}")

        artifact_uuid = uuid.uuid4().hex[:8]
        staging = self.output_root / f".working_{artifact_uuid}"
        try:
            input_dir = staging / "00_input"
            input_dir.mkdir(parents=True, exist_ok=False)
            copied_path = input_dir / target.source_path.name

            digest = hashlib.sha256()
            size_bytes = 0
            with target.source_path.open("rb") as source, copied_path.open("xb") as destination:
                while chunk := source.read(_COPY_CHUNK_SIZE):
                    destination.write(chunk)
                    digest.update(chunk)
                    size_bytes += len(chunk)

            sha256 = digest.hexdigest()
            validation = validate_saved_file(copied_path, size_bytes, ".pdf")
            if not validation.ok:
                raise ValueError(f"복사한 PDF 검증 실패: {validation.reason}")

            for child in (
                "01_extracted",
                "02_images",
                "02_tables",
                "03_processed",
                "90_debug",
                "99_result",
            ):
                (staging / child).mkdir(exist_ok=True)

            source = {
                "source_kind": target.source_kind,
                "source_path": str(target.source_path),
                "original_filename": target.source_path.name,
                "copied_path": copied_path.relative_to(staging).as_posix(),
                "sha256": sha256,
                "size_bytes": size_bytes,
            }
            if target.document_key is not None:
                source["document_key"] = target.document_key
            if target.product_version_key is not None:
                source["product_version_key"] = target.product_version_key
            self.write_json(
                staging / "99_result" / "load_manifest.json",
                {
                    "schema_version": LOAD_SCHEMA_VERSION,
                    "versions": {
                        "loader": LOADER_VERSION,
                        "parser": PARSER_VERSION,
                    },
                    "artifact_id": artifact_id,
                    "created_at": created_at.isoformat(timespec="milliseconds"),
                    "completed_at": None,
                    "status": "RUNNING",
                    "source": source,
                    "summary": {},
                    "artifacts": {
                        "input_pdf": copied_path.relative_to(staging).as_posix(),
                        "raw_pages": "01_extracted/pages.jsonl",
                        "raw_pages_dir": "01_extracted/pages",
                        "processed_pages": "03_processed/pages.jsonl",
                        "processed_pages_dir": "03_processed/pages",
                        "processed_tables_dir": "03_processed/tables",
                        "tables": "02_tables/tables.jsonl",
                        "images": "02_images/images.jsonl",
                        "warnings": "99_result/warnings.jsonl",
                        "raw_text": "01_extracted/raw_text.txt",
                        "content_markdown": "03_processed/content.md",
                        "header_footer_analysis": "90_debug/header_footer_analysis.json",
                        "cropped_pdf": None,
                    },
                    "error": None,
                },
            )
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
        return PreparedLoadItem(
            target=target,
            item_dir=staging,
            final_item_dir=final_item_dir,
            copied_pdf_path=copied_path,
            sha256=sha256,
            size_bytes=size_bytes,
        )

    @staticmethod
    def finalize_item(prepared: PreparedLoadItem) -> Path:
        """작업 폴더를 최종 위치로 멱등적으로 공개한다.

        Windows에서는 백신·검색 인덱서 등이 막 생성된 파일을 잠시 점유해
        디렉터리 rename이 접근 거부 또는 공유 위반으로 실패할 수 있다. 이런
        일시 오류만 제한적으로 재시도하고, rename이 실제로 완료된 뒤 예외가
        전달된 경우에는 디렉터리 상태를 확인해 성공으로 판정한다.
        """

        staging = prepared.item_dir
        final = prepared.final_item_dir

        staging_exists = staging.exists()
        final_exists = final.exists()
        if final_exists:
            if staging_exists:
                raise FileExistsError(
                    f"작업 폴더와 최종 폴더가 모두 존재합니다: {staging}, {final}"
                )
            return final
        if not staging_exists:
            raise FileNotFoundError(f"작업 폴더를 찾을 수 없습니다: {staging}")

        max_attempts = len(_FINALIZE_RETRY_DELAYS) + 1
        for attempt in range(max_attempts):
            try:
                staging.rename(final)
            except OSError as exc:
                staging_exists = staging.exists()
                final_exists = final.exists()
                if final_exists and not staging_exists:
                    return final
                if final_exists and staging_exists:
                    raise FileExistsError(
                        f"작업 폴더와 최종 폴더가 모두 존재합니다: {staging}, {final}"
                    ) from exc
                if not staging_exists:
                    raise FileNotFoundError(
                        f"rename 실패 후 작업 폴더가 사라졌습니다: {staging}"
                    ) from exc

                winerror = getattr(exc, "winerror", None)
                retryable = isinstance(exc, PermissionError) or (
                    winerror in _WINDOWS_RETRYABLE_RENAME_ERRORS
                )
                if not retryable or attempt + 1 >= max_attempts:
                    raise
                time.sleep(_FINALIZE_RETRY_DELAYS[attempt])
                continue

            if final.exists() and not staging.exists():
                return final
            raise OSError(
                f"rename 이후 최종 폴더 상태를 확인할 수 없습니다: {staging}, {final}"
            )

        raise AssertionError("unreachable")

    def save_parse_output(self, prepared: PreparedLoadItem, output: PdfParseOutput) -> None:
        item_dir = prepared.item_dir
        extracted_dir = item_dir / "01_extracted"
        tables_dir = item_dir / "02_tables"
        processed_dir = item_dir / "03_processed"
        debug_dir = item_dir / "90_debug"
        result_dir = item_dir / "99_result"
        raw_pages_dir = extracted_dir / "pages"
        processed_pages_dir = processed_dir / "pages"

        raw_pages_dir.mkdir(exist_ok=True)
        processed_pages_dir.mkdir(exist_ok=True)

        raw_page_rows: list[dict[str, Any]] = []
        processed_page_rows: list[dict[str, Any]] = []
        for page in output.pages:
            page_stem = f"page_{page.page_no:04d}"
            raw_page_path = raw_pages_dir / f"{page_stem}.txt"
            processed_markdown_path = processed_pages_dir / f"{page_stem}.md"

            self.write_text(raw_page_path, page.text_raw)
            self.write_text(processed_markdown_path, page.content_markdown)

            raw_page_rows.append(
                {
                    "page_no": page.page_no,
                    "width": page.width,
                    "height": page.height,
                    "text_raw": page.text_raw,
                    "text_raw_path": raw_page_path.relative_to(item_dir).as_posix(),
                    "meaningful_character_count": page.meaningful_character_count,
                    "word_count": page.word_count,
                    "image_count": page.image_count,
                    "largest_image_area_ratio": page.largest_image_area_ratio,
                    "page_status": page.page_status,
                    "warnings": page.warnings,
                }
            )
            processed_page_rows.append(
                {
                    "page_no": page.page_no,
                    "text_content": page.text_content,
                    "content_markdown": page.content_markdown,
                    "content_markdown_path": processed_markdown_path.relative_to(
                        item_dir
                    ).as_posix(),
                    "table_refs": page.table_refs,
                    "image_refs": page.image_refs,
                }
            )

        self.write_text(extracted_dir / "raw_text.txt", output.raw_text)
        self.write_text(processed_dir / "content.md", output.content_markdown)
        self.write_jsonl(extracted_dir / "pages.jsonl", raw_page_rows)
        self.write_jsonl(processed_dir / "pages.jsonl", processed_page_rows)
        self.write_jsonl(
            item_dir / "02_images" / "images.jsonl",
            (asdict(image) for image in output.images),
        )
        table_rows: list[dict[str, Any]] = []
        for table in output.tables:
            table_row: dict[str, Any] = {
                "table_id": table.table_id,
                "page_no": table.page_no,
                "table_index": table.table_index,
                "bbox": table.bbox,
                "row_count": table.row_count,
                "column_count": table.column_count,
                "quality_status": table.quality_status,
                "quality_reason": table.quality_reason,
                "files": {
                    "markdown": table.markdown_path or None,
                    "xlsx": table.xlsx_path or None,
                    "png": table.rendered_image_path or None,
                    "processed_markdown": table.processed_markdown_path or None,
                },
                "contained_by": table.contained_by,
                "included_in_page": table.included_in_page,
            }
            if table.reconstruction:
                table_row["reconstruction"] = table.reconstruction
            table_rows.append(table_row)
        self.write_jsonl(tables_dir / "tables.jsonl", table_rows)
        self.write_json(debug_dir / "header_footer_analysis.json", output.header_footer_analysis)
        self.write_jsonl(result_dir / "warnings.jsonl", output.warnings)
        manifest_path = result_dir / "load_manifest.json"
        manifest = self.read_json(manifest_path)
        manifest["summary"] = {
            "page_count": len(output.pages),
            "ocr_required_pages": output.ocr_required_pages,
            "empty_pages": output.empty_pages,
            "page_status_counts": output.page_status_counts,
            "detected_table_count": output.detected_table_count,
            "table_count": len(output.tables),
            "fragment_table_count": output.fragment_table_count,
            "rejected_table_count": output.rejected_table_count,
            "table_image_count": sum(
                1 for table in output.tables if table.rendered_image_path
            ),
            "image_count": len(output.images),
            "image_occurrence_count": sum(
                len(image.occurrences) for image in output.images
            ),
            "effective_text_length": output.effective_text_length,
            "text_source": output.text_source,
            "table_reconstruction": {
                "enabled": output.table_reconstruction_enabled,
                **output.table_reconstruction_summary,
            },
        }
        manifest["artifacts"]["cropped_pdf"] = (
            output.cropped_pdf_path.as_posix()
            if output.cropped_pdf_path is not None
            else None
        )
        self.write_json(manifest_path, manifest)

    def save_item_result(self, prepared: PreparedLoadItem, payload: dict[str, Any]) -> None:
        manifest_path = prepared.item_dir / "99_result" / "load_manifest.json"
        manifest = self.read_json(manifest_path)
        manifest["status"] = payload["status"]
        manifest["completed_at"] = _now().isoformat(timespec="milliseconds")
        error_stage = payload.get("error_stage")
        error_code = payload.get("error_code")
        error_message = payload.get("error_message")
        manifest["error"] = (
            {
                "stage": error_stage,
                "code": error_code,
                "message": error_message,
            }
            if any(value is not None for value in (error_stage, error_code, error_message))
            else None
        )
        self.write_json(manifest_path, manifest)

    @staticmethod
    def read_json(path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"JSON 객체가 필요합니다: {path}")
        return payload

    @staticmethod
    def write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)

    @staticmethod
    def write_jsonl(path: Path, rows: Iterable[Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with temp_path.open("w", encoding="utf-8", newline="\n") as fp:
            for row in rows:
                fp.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")
        temp_path.replace(path)

    @staticmethod
    def write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(path)
