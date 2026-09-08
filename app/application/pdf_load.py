"""명시된 PDF들을 독립적으로 복사·파싱·저장하는 Load 유스케이스."""

from __future__ import annotations

import logging
from typing import Callable

from app.core.ipr_logger import get_logger, push_trace_id, reset_trace_id
from app.domain.llm import TableReconstructor
from app.domain.pdf_load import (
    LoadStatus,
    PdfLoadItemResult,
    PdfLoadRequest,
    PdfLoadResult,
    PdfParseOutput,
    RunStatus,
)
from app.infrastructure.artifacts import PdfLoadArtifactRepository
from app.infrastructure.document_source.local_pdf import LocalPdfSelector, PdfInputError
from app.infrastructure.pdf import PdfParser
from app.load_settings import PdfLoadSettings


CORE_EXTRACTION_WARNING_CODES = frozenset(
    {
        "TABLE_DETECTION_FAILED",
        "TABLE_EXTRACTION_FAILED",
        "IMAGE_EXTRACTION_UNAVAILABLE",
        "IMAGE_DETECTION_FAILED",
        "IMAGE_EXTRACTION_FAILED",
        "TABLE_RECONSTRUCTION_FALLBACK",
    }
)


class PdfLoadApplication:
    def __init__(
        self,
        *,
        selector: LocalPdfSelector | None = None,
        artifact_repository: PdfLoadArtifactRepository | None = None,
        parser_factory: Callable[[], PdfParser] | None = None,
        header_footer_enabled: bool | None = None,
        table_reconstructor: TableReconstructor | None = None,
    ) -> None:
        self.selector = selector or LocalPdfSelector()
        self.artifacts = artifact_repository or PdfLoadArtifactRepository()
        self.header_footer_enabled = (
            PdfLoadSettings.from_env().header_footer_enabled
            if header_footer_enabled is None
            else header_footer_enabled
        )
        self.parser_factory = parser_factory or self._default_parser_factory
        self.table_reconstructor = table_reconstructor

    def _default_parser_factory(self) -> PdfParser:
        from app.infrastructure.pdf.prosure.parser import ProSurePdfParser

        return ProSurePdfParser(
            header_footer_enabled=self.header_footer_enabled,
            table_reconstructor=self.table_reconstructor,
        )

    def run(self, request: PdfLoadRequest) -> PdfLoadResult:
        targets = self.selector.select(request.pdf_paths)
        logger = get_logger(__name__)
        results: list[PdfLoadItemResult] = []

        logger.info("PDF Load 시작: inputs=%d", len(targets))
        try:
            for target in targets:
                result = self._load_one(target, logger)
                results.append(result)

            status = self._run_status(results)
            logger.info("PDF Load 종료: status=%s", status.value)
            return PdfLoadResult(status=status, items=results)
        finally:
            close = getattr(self.table_reconstructor, "close", None)
            if callable(close):
                close()

    def _load_one(self, target, logger: logging.Logger) -> PdfLoadItemResult:
        prepared = None
        trace_token = None
        stage = "VALIDATE_INPUT"
        try:
            self.selector.validate(target)
            stage = "COPY_INPUT"
            prepared = self.artifacts.prepare_item(target)
            trace_token = push_trace_id(prepared.final_item_dir.name)
            stage = "INITIALIZE_PARSER"
            parser = self.parser_factory()
            stage = "PARSE_PDF"
            output: PdfParseOutput = parser.parse(
                source_pdf=prepared.copied_pdf_path,
                item_dir=prepared.item_dir,
            )
            stage = "SAVE_ARTIFACTS"
            self.artifacts.save_parse_output(prepared, output)
            status = self._item_status(output)
            result = PdfLoadItemResult(
                input_index=target.input_index,
                source_path=str(target.source_path),
                status=status,
                item_dir=str(prepared.final_item_dir),
                sha256=prepared.sha256,
                page_count=len(output.pages),
                table_count=len(output.tables),
                image_count=len(output.images),
                table_image_count=sum(
                    1 for table in output.tables if table.rendered_image_path
                ),
                effective_text_length=output.effective_text_length,
                ocr_required_pages=output.ocr_required_pages,
                empty_pages=output.empty_pages,
                page_status_counts=output.page_status_counts,
            )
            self.artifacts.save_item_result(prepared, result.as_dict())
            stage = "FINALIZE_ARTIFACTS"
            self.artifacts.finalize_item(prepared)
            logger.info(
                "PDF Load 항목 완료: index=%03d status=%s pages=%d tables=%d images=%d table_images=%d file=%s",
                target.input_index,
                status.value,
                len(output.pages),
                len(output.tables),
                len(output.images),
                sum(1 for table in output.tables if table.rendered_image_path),
                target.source_path,
            )
            return result
        except Exception as exc:  # 각 PDF 실패를 격리해 다음 입력을 계속 처리한다.
            code = exc.code if isinstance(exc, PdfInputError) else type(exc).__name__
            failed_item_dir = None
            if prepared is not None:
                failed_item_dir = (
                    prepared.item_dir
                    if stage == "FINALIZE_ARTIFACTS" and prepared.item_dir.exists()
                    else prepared.final_item_dir
                )
            result = PdfLoadItemResult(
                input_index=target.input_index,
                source_path=str(target.source_path),
                status=LoadStatus.FAILED,
                item_dir=str(failed_item_dir) if failed_item_dir is not None else None,
                sha256=prepared.sha256 if prepared is not None else None,
                error_stage=stage,
                error_code=str(code),
                error_message=str(exc),
            )
            if prepared is not None:
                try:
                    if prepared.item_dir.exists():
                        self.artifacts.save_item_result(prepared, result.as_dict())
                        # FINALIZE_ARTIFACTS는 저장소가 이미 제한된 재시도를 모두
                        # 수행했다. 여기서 다시 rename하면 최대 시도 횟수를 깨고,
                        # 두 번째 시도에서 폴더만 이동된 FAILED 결과가 생길 수 있다.
                        if stage != "FINALIZE_ARTIFACTS":
                            self.artifacts.finalize_item(prepared)
                except Exception:
                    logger.exception("PDF Load 실패 산출물 저장 실패: file=%s", target.source_path)
            logger.exception(
                "PDF Load 항목 실패: index=%03d stage=%s file=%s",
                target.input_index,
                stage,
                target.source_path,
            )
            return result
        finally:
            if trace_token is not None:
                reset_trace_id(trace_token)

    @staticmethod
    def _item_status(output: PdfParseOutput) -> LoadStatus:
        counts = output.page_status_counts
        text_pages = counts.get("TEXT", 0)
        ocr_pages = counts.get("OCR_REQUIRED", 0)
        if ocr_pages and text_pages:
            return LoadStatus.PARTIAL
        if ocr_pages or not text_pages:
            return LoadStatus.OCR_REQUIRED
        warning_codes = {
            str(warning.get("code", "")) for warning in output.warnings
        }
        if warning_codes & CORE_EXTRACTION_WARNING_CODES:
            return LoadStatus.PARTIAL
        return LoadStatus.SUCCEEDED

    @staticmethod
    def _run_status(items: list[PdfLoadItemResult]) -> RunStatus:
        if items and all(item.status is LoadStatus.SUCCEEDED for item in items):
            return RunStatus.SUCCEEDED
        if items and all(item.status is LoadStatus.FAILED for item in items):
            return RunStatus.FAILED
        return RunStatus.PARTIAL

__all__ = [
    "PdfLoadApplication",
    "PdfLoadRequest",
    "PdfLoadResult",
]
