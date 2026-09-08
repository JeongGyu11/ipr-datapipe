"""문서 다운로드 - 검증, 중복 처리, DB 상태 반영."""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from crawler.base_adapter import BaseInsurerAdapter
from crawler.config import AppConfig
from crawler.manifest_service import ManifestRecord, ManifestService, fmt_date
from crawler.path_service import PathService
from crawler.plan_service import PlanService
from crawler.validators import validate_response, validate_saved_file
from models.document import Document, DocumentType, DownloadStatus
from models.product_version import ProductVersion
from utils.file_utils import filename_from_url, guess_extension, normalize_storage_component
from utils.hash_utils import sha256_bytes, sha256_file
from utils.crawler_logger import ErrorRecorder, get_logger
from utils.network_io import (
    retry_file_operation,
    safe_fsync,
    safe_unlink,
    strict_exists,
)


@dataclass
class DownloadService:
    config: AppConfig
    paths: PathService
    manifest: ManifestService
    errors: ErrorRecorder
    dry_run: bool = False
    retry_failed_only: bool = False
    # 선택적으로 수집 결과를 장기 백필 plan에 동시에 기록한다.
    # 기본값 None이면 plan을 별도로 기록하지 않는다.
    plan_service: PlanService | None = None
    outbox: object | None = None

    def __post_init__(self):
        self.log = get_logger()

    def _db_payload(
        self,
        version: ProductVersion,
        document: Document | None,
        record: ManifestRecord,
    ) -> dict:
        """repository에 전달할 풍부한 문서 상태 payload를 만든다.

        repository 구현이 아직 바뀌는 동안에도 ``record``와 원본 모델을
        모두 제공하여 키 생성/POST download hint를 잃지 않게 한다.
        """
        from crawler.document_repository import payload_from_record

        return payload_from_record(
            record,
            version=version,
            document=document,
            run_id=self.manifest.run_id,
        )

    def _db_call(self, method: str, payload: dict) -> None:
        repository = getattr(self.manifest, "repository", None)
        if repository is None:
            return
        writer = getattr(repository, method, None)
        if not callable(writer):
            raise AttributeError(f"DB repository에 {method} API가 없습니다")
        # repository 쓰기 API는 평탄화된 payload 단일 인자 계약이다.
        # TypeError를 다른 호출 형태로 재시도하지 않는다. 내부 버그를
        # signature 불일치로 오인하여 중복 반영하는 것을 막기 위해서다.
        try:
            writer(payload)
        except Exception as exc:
            # 재연결 후 동일 이벤트를 재생할 수 있는 연결 장애만 outbox에
            # 보존한다. SQL/제약/payload 오류는 자동 복구되지 않으며 poison
            # 이벤트가 되므로 즉시 fail-closed하고 코드/스키마를 수정한다.
            from crawler.db_outbox import is_transient_database_error

            if self.outbox is not None and is_transient_database_error(exc):
                event = {"operation": method, "payload": self._json_safe(payload)}
                self.outbox.append(event)
            raise

    @staticmethod
    def _json_safe(value):
        from datetime import date, datetime
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): DownloadService._json_safe(child) for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return [DownloadService._json_safe(child) for child in value]
        if hasattr(value, "to_row"):
            return DownloadService._json_safe(value.to_row())
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def _upsert_seen(
        self,
        version: ProductVersion,
        document: Document | None,
        record: ManifestRecord,
    ) -> None:
        """terminal과 동일한 identity record로 PENDING을 먼저 확정한다."""
        payload = self._db_payload(version, document, record)
        payload.update(
            file_status="PENDING",
            last_attempt_status=None,
            error_message=None,
            downloaded_at=None,
            last_download_run_id=None,
        )
        self._db_call("upsert_seen", payload)

    def _add(
        self,
        version: ProductVersion,
        document: Document | None,
        record: ManifestRecord,
    ) -> ManifestRecord:
        """메모리 실행 집계와 DB terminal 상태를 같은 지점에서 확정한다."""
        result = self.manifest.add(record)
        # 회사 전체 오류는 manager가 직접 기록하므로 이 경로에 들어오지
        # 않는다. 문서 링크가 없는 상품 버전은 document_type=NULL인
        # 합성 문서 행으로 DB에 남겨 재수집 대상과 최신 상태를 보존한다.
        # DRY_RUN도 문서 발견/예상 결과를 DB에 남긴다. repository의 조건부
        # UPSERT는 DRY_RUN일 때만 기존 AVAILABLE 파일 증거를 보존하고,
        # 실제 새 실패/손상 결과는 최신 물리 상태로 반영한다.
        self._db_call("upsert_result", self._db_payload(version, document, result))
        return result

    def process_plan(
        self,
        adapter: BaseInsurerAdapter,
        plan,
    ) -> list[ManifestRecord]:
        """영속 plan을 사용해 재수집 없이 문서를 다운로드한다.

        ``plan``은 :class:`crawler.plan_service.PlanService` 인스턴스나 plan
        JSONL 경로 모두 받을 수 있다. 상품 상세를 다시 호출하지 않고 plan의
        메타데이터를 ``ProductVersion``/``Document``로 복원한 뒤 기존
        ``process_document`` 경로를 그대로 사용하므로 DB 체크포인트와
        파일 검증 규칙이 유지된다. 성공 항목은 plan state 저널에도 기록되어
        프로세스가 중단된 뒤 실패/미처리 항목만 재개할 수 있다.
        """
        plan_service = plan if isinstance(plan, PlanService) else PlanService(plan)
        items = plan_service.pending_items()
        records: list[ManifestRecord] = []
        for item in items:
            version = item.to_version()
            version.extra = {**(version.extra or {}), "_plan_checkpoint_key": item.plan_key}
            document = item.to_document()
            # process_plan owns the plan item selected above, so defer the
            # automatic range-collection hook and journal this item exactly
            # once below.
            record = self.process_document(adapter, version, document, update_plan=False)
            plan_service.mark_result(item, record)
            records.append(record)
        return records

    # ------------------------------------------------------------------
    def process_version(self, adapter: BaseInsurerAdapter, version: ProductVersion) -> list[ManifestRecord]:
        """상품 버전 1건의 모든 문서를 처리한다."""
        documents = adapter.collect_documents(version)

        # 날짜를 전혀 알 수 없는 버전 -> 제외하지 않고 MANUAL_REVIEW_REQUIRED 로 기록
        if version.needs_manual_review:
            base = self._base_record(version)
            base.download_status = DownloadStatus.MANUAL_REVIEW_REQUIRED
            base.error_message = "날짜 정보를 확인할 수 없어 대상 월 판단 불가"
            if not documents:
                self._upsert_seen(version, None, base)
                return [self._add(version, None, base)]
            records = []
            for document in documents:
                record = self._base_record(version, document)
                record.download_status = DownloadStatus.MANUAL_REVIEW_REQUIRED
                record.error_message = "날짜 정보를 확인할 수 없어 대상 월 판단 불가"
                self._upsert_seen(version, document, record)
                record = self._add(version, document, record)
                self._mark_plan_result(version, document, record)
                records.append(record)
            return records

        if not documents:
            record = self._base_record(version)
            record.download_status = DownloadStatus.NO_DOCUMENT_LINK
            record.error_message = "수집 대상 문서 링크 없음"
            self._upsert_seen(version, None, record)
            return [self._add(version, None, record)]

        return [self.process_document(adapter, version, d) for d in documents]

    # ------------------------------------------------------------------
    def process_document(
        self,
        adapter: BaseInsurerAdapter,
        version: ProductVersion,
        document: Document,
        *,
        update_plan: bool = True,
    ) -> ManifestRecord:
        record = self._process_document(adapter, version, document)
        if update_plan:
            self._mark_plan_result(version, document, record)
        return record

    def _process_document(
        self,
        adapter: BaseInsurerAdapter,
        version: ProductVersion,
        document: Document,
    ) -> ManifestRecord:
        record = self._base_record(version, document)

        # 문서 링크 없음
        if not document.has_link:
            record.download_status = DownloadStatus.NO_DOCUMENT_LINK
            record.error_message = "문서 링크가 제공되지 않음"
            self._upsert_seen(version, document, record)
            return self._add(version, document, record)

        # 체크포인트: 이미 성공한 문서는 다시 받지 않는다.
        previous = self.manifest.previous_row(record)
        if previous is None:
            # legacy manifest/DB에는 redirect 이후 final URL로 key가 저장돼
            # 있지만 사이트 목록은 매번 origin URL을 줄 수 있다. 문맥상
            # 정확히 한 행만 대응하면 fetch 전부터 기존 final identity를
            # 이어받아 파일 재사용·실패 기록 모두 같은 key에 남긴다.
            previous = self._unique_context_row(record)
            # v4 keeps the current source URL in document_url; a legacy
            # redirect row is only used as a checkpoint/file hint and must not
            # overwrite the source metadata with its final URL.
        if previous:
            status = previous.get("download_status", "")
            if status in DownloadStatus.COMPLETED and self._previous_file_ok(previous):
                return self._reuse_previous_file(version, document, record, previous)
            if self.retry_failed_only and not (
                status in DownloadStatus.RETRYABLE
                or status in DownloadStatus.COMPLETED
            ):
                return self._skip_retry_only(version, document, record)
        elif self.retry_failed_only:
            return self._skip_retry_only(version, document, record)

        # 문서유형 미확인은 다운로드하지 않고 상태만 남긴다.
        if document.document_type == DocumentType.UNKNOWN:
            record.download_status = DownloadStatus.UNKNOWN_DOCUMENT_TYPE
            record.error_message = f"문서유형 판별 불가: {document.document_label!r}"
            self.errors.record(
                company=version.company_code,
                product=version.product_name_raw,
                label=document.document_label,
                url=document.document_url,
                status=DownloadStatus.UNKNOWN_DOCUMENT_TYPE,
            )
            self._upsert_seen(version, document, record)
            return self._add(version, document, record)

        # dry-run: 실제 파일을 받지 않고 예상 경로만 계산
        if self.dry_run:
            # 서버가 알려준 원본 파일명이 가장 정확하다.
            # (다운로드 URL 경로 확장자는 .do/.ec 처럼 서블릿 확장자인 경우가 많다)
            extension = (
                guess_extension(url=document.original_filename)
                or guess_extension(url=document.document_url)
                or ".pdf"
            )
            original_filename = document.original_filename or filename_from_url(document.document_url)
            if original_filename and not record.original_filename:
                record.original_filename = original_filename
            target, filename = self.paths.resolve_target_path(
                version, document.document_type, extension, original_filename
            )
            record.download_status = DownloadStatus.DRY_RUN
            record.file_extension = extension
            record.saved_filename = filename
            self._set_saved_path(record, target)
            self._upsert_seen(version, document, record)
            return self._add(version, document, record)

        return self._download(adapter, version, document, record)

    def _reuse_previous_file(
        self,
        version: ProductVersion,
        document: Document,
        record: ManifestRecord,
        previous: dict,
    ) -> ManifestRecord:
        """검증된 기존 파일을 같은 DB identity의 완료 결과로 재사용한다."""
        record.download_status = DownloadStatus.DUPLICATE_SKIPPED
        record.saved_filename = previous.get("saved_filename", "")
        self._set_saved_path(record, previous.get("saved_relative_path", ""))
        record.sha256 = previous.get("sha256", "")
        record.file_size = previous.get("file_size", "")
        record.file_extension = previous.get("file_extension", "")
        record.content_type = previous.get("content_type", "")
        record.error_message = "이전 실행에서 이미 수집됨(체크포인트)"
        self._upsert_seen(version, document, record)
        return self._add(version, document, record)

    def _skip_retry_only(
        self,
        version: ProductVersion,
        document: Document,
        record: ManifestRecord,
    ) -> ManifestRecord:
        record.download_status = DownloadStatus.DUPLICATE_SKIPPED
        record.error_message = "--retry-failed: 이전 실패 기록 없음"
        self._upsert_seen(version, document, record)
        return self._add(version, document, record)

    def _unique_context_row(self, record: ManifestRecord) -> dict | None:
        """URL만 달라진 legacy redirect 행을 문맥이 유일할 때 찾는다."""
        fields = (
            "company_code",
            "source_product_id",
            "product_name_raw",
            "target_date",
            "document_type",
        )
        expected = tuple(str(getattr(record, field, "") or "") for field in fields)
        expected_url = str(record.document_url or "")
        expected_checkpoint = str(record.checkpoint_key or "")
        matches: list[dict] = []
        for row in self.manifest.previous.values():
            row_url = str(row.get("document_url") or "")
            row_checkpoint = str(row.get("checkpoint_key") or "")
            # 이 보정은 URL redirect에만 적용한다. PLAN/checkpoint 또는
            # 파일명 기반 문서를 같은 상품 문맥이라는 이유로 합치면 안 된다.
            if expected_checkpoint or row_checkpoint:
                continue
            if not expected_url or not row_url or expected_url == row_url:
                continue
            current = tuple(str(row.get(field, "") or "") for field in fields)
            if current != expected:
                continue
            # 원문 label/파일명이 양쪽에 모두 있으면 일치해야 한다.
            if any(
                str(row.get(field, "") or "")
                and str(getattr(record, field, "") or "")
                and str(row.get(field, "")) != str(getattr(record, field, ""))
                for field in ("document_label", "original_filename")
            ):
                continue
            matches.append(row)
            if len(matches) > 1:
                return None
        return matches[0] if matches else None

    def _mark_plan_result(
        self,
        version: ProductVersion,
        document: Document,
        record: ManifestRecord,
    ) -> None:
        """범위 수집과 동시에 canonical plan/state를 갱신한다."""
        if self.plan_service is None or not document.has_link:
            return
        item = self.plan_service.ensure_version(version, document)
        self.plan_service.mark_result(item, record)

    # ------------------------------------------------------------------
    def _download(
        self,
        adapter: BaseInsurerAdapter,
        version: ProductVersion,
        document: Document,
        record: ManifestRecord,
    ) -> ManifestRecord:
        # v4 identity는 fetch 전에 확정한다. POST adapter의 상수 endpoint나
        # HTTP redirect final URL은 document_key에 포함되지 않는다.
        self._upsert_seen(version, document, record)
        result = adapter.fetch_document(document)
        record.content_type = result.content_type
        if result.original_filename:
            record.original_filename = result.original_filename
        if result.final_url:
            # final_url은 추적용 metadata일 뿐 identity/document_url을
            # 변경하지 않는다. 원본 URL은 PENDING 시점에 이미 기록됐다.
            record.final_url = result.final_url

        if not result.ok:
            record.download_status = result.status or DownloadStatus.DOWNLOAD_FAILED
            record.error_message = result.reason or f"HTTP {result.http_status}"
            self._log_error(version, document, record)
            return self._add(version, document, record)

        extension = (
            guess_extension(url=result.original_filename)
            or guess_extension(url=document.original_filename)
            or guess_extension(url=document.document_url)
            or guess_extension(content_type=result.content_type)
            or ".pdf"
        )
        record.file_extension = extension

        original_filename = (
            result.original_filename
            or document.original_filename
            or filename_from_url(document.document_url)
        )
        if original_filename:
            record.original_filename = original_filename

        validation = validate_response(
            status_code=result.http_status or 200,
            content_type=result.content_type,
            data=result.content,
            extension=extension,
            allowed_content_types=self.config.allowed_content_types,
            allowed_extensions=self.config.allowed_extensions,
        )
        if not validation.ok:
            record.download_status = validation.status
            record.error_message = validation.reason
            record.file_size = len(result.content)
            self._log_error(version, document, record)
            return self._add(version, document, record)

        digest = sha256_bytes(result.content)
        target, filename = self.paths.resolve_target_path(
            version, document.document_type, extension, original_filename
        )
        try:
            retry_file_operation(
                lambda: target.parent.mkdir(parents=True, exist_ok=True),
                path=target.parent,
                operation_name="최종 디렉터리 생성",
            )
        except OSError as exc:
            return self._storage_failure(version, document, record, exc)

        # 동일 파일명이 있으면 해시 비교 -> 같으면 생략, 다르면 _2, _3 …
        try:
            target_exists = retry_file_operation(
                lambda: strict_exists(target),
                path=target,
                operation_name="기존 파일 확인",
            )
            if target_exists:
                if retry_file_operation(
                    lambda: sha256_file(target),
                    path=target,
                    operation_name="기존 파일 SHA-256 계산",
                ) == digest:
                    record.download_status = DownloadStatus.DUPLICATE_SKIPPED
                    record.saved_filename = target.name
                    self._set_saved_path(record, target)
                    record.sha256 = digest
                    record.file_size = retry_file_operation(
                        lambda: target.stat().st_size,
                        path=target,
                        operation_name="기존 파일 크기 확인",
                    )
                    record.error_message = "동일 해시 파일이 이미 존재하여 다운로드 생략"
                    return self._add(version, document, record)
                target = self._next_available_path_with_retry(target)
                filename = target.name
        except OSError as exc:
            return self._storage_failure(version, document, record, exc)

        try:
            target = self._publish_validated_file(
                content=result.content,
                target=target,
                extension=extension,
                digest=digest,
                run_id=self.manifest.run_id,
                company_code=version.company_code,
            )
            filename = target.name
        except OSError as exc:
            record.download_status = DownloadStatus.DOWNLOAD_FAILED
            record.error_message = f"파일 저장 실패: {exc}"
            self._log_error(version, document, record)
            return self._add(version, document, record)

        try:
            saved_check = self._validate_saved_file_with_retry(
                target, len(result.content), extension, "최종 파일"
            )
        except OSError as exc:
            record.saved_filename = filename
            self._set_saved_path(record, target)
            return self._storage_failure(version, document, record, exc)
        if not saved_check.ok:
            record.download_status = saved_check.status
            record.error_message = saved_check.reason
            record.saved_filename = filename
            self._set_saved_path(record, target)
            self._log_error(version, document, record)
            return self._add(version, document, record)

        record.download_status = DownloadStatus.SUCCESS
        record.saved_filename = filename
        self._set_saved_path(record, target)
        record.sha256 = digest
        record.file_size = len(result.content)
        return self._add(version, document, record)

    def _publish_validated_file(
        self,
        *,
        content: bytes,
        target: Path,
        extension: str,
        digest: str,
        run_id: str,
        company_code: str,
    ) -> Path:
        """검증한 파일을 최종 경로에 반영한다.

        로컬 출력은 same-volume rename을 사용하고, 네트워크 출력은 로컬 staging
        검증 후 서버 임시 파일로 복사해 같은 공유 볼륨 안에서 이동한다.
        호출자는 해당 보험사의 CompanyLock을 보유한다고 가정하며, 검증되지
        않은 파일은 최종 문서 폴더에 생성하지 않는다.
        """
        # 로컬 출력 테스트에서는 기존 same-volume 경로를 유지한다. 실제
        # 네트워크 출력은 local staging에서 검증한 뒤 서버 임시 파일로 복사한다.
        if self.paths.is_network_output:
            return self._publish_from_local_to_network(
                content=content,
                target=target,
                extension=extension,
                digest=digest,
                run_id=run_id,
                company_code=company_code,
            )

        staging_dir = self.paths.download_staging_dir(run_id, company_code)
        staging_dir.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        part_path = staging_dir / (
            f".part_{normalize_storage_component(run_id)}_{uuid.uuid4().hex[:12]}{extension}"
        )
        try:
            with open(part_path, "xb") as fp:
                fp.write(content)
                fp.flush()
                safe_fsync(fp, path=part_path)

            part_check = self._validate_saved_file_with_retry(
                part_path, len(content), extension, "staging"
            )
            if not part_check.ok:
                raise OSError(f"staging 파일 검증 실패: {part_check.reason}")
            if sha256_file(part_path) != digest:
                raise OSError("staging 파일 SHA-256 불일치")

            # 보험사 잠금 밖의 수동 파일 생성에도 덮어쓰지 않도록 최종 직전에 재확인한다.
            if retry_file_operation(
                lambda: strict_exists(target),
                path=target,
                operation_name="최종 대상 파일 확인",
            ):
                target = self._next_available_path_with_retry(target)
            published_new_target = not retry_file_operation(
                lambda: strict_exists(target),
                path=target,
                operation_name="최종 대상 파일 재확인",
            )
            # 같은 볼륨 안의 원자적 rename을 사용한다. Windows의 os.rename은
            # 목적지가 이미 생겼으면 실패하므로 수동 생성 파일도 덮어쓰지 않는다.
            os.rename(part_path, target)
            part_path = None

            final_check = self._validate_saved_file_with_retry(
                target, len(content), extension, "최종 파일"
            )
            if not final_check.ok or sha256_file(target) != digest:
                # 검증 실패 시 이번 publish에서 새로 만든 경로만 제거한다.
                # 기존 파일을 실수로 삭제하지 않도록 존재 여부를 기억한다.
                if published_new_target:
                    safe_unlink(target)
                reason = final_check.reason if not final_check.ok else "SHA-256 불일치"
                raise OSError(f"최종 파일 검증 실패: {reason}")
            return target
        finally:
            if part_path is not None:
                try:
                    safe_unlink(part_path)
                except OSError:
                    self.log.warning("staging 임시 파일 정리 실패: %s", part_path)
            self._cleanup_empty_staging_dirs(staging_dir)

    def _publish_from_local_to_network(
        self,
        *,
        content: bytes,
        target: Path,
        extension: str,
        digest: str,
        run_id: str,
        company_code: str,
    ) -> Path:
        """로컬 검증 파일을 서버 staging으로 복사한 뒤 원자적으로 반영한다.

        서버 staging과 최종 문서 루트는 같은 output share를 사용하므로
        마지막 rename은 cross-volume 복사가 아닌 atomic move가 된다.
        """

        staging_dir = self.paths.download_staging_dir(run_id, company_code)
        server_staging_dir = self.paths.server_upload_staging_dir(run_id, company_code)
        retry_file_operation(
            lambda: staging_dir.mkdir(parents=True, exist_ok=True),
            path=staging_dir,
            operation_name="로컬 staging 디렉터리 생성",
        )
        local_part = staging_dir / (
            f".part_{normalize_storage_component(run_id)}_{uuid.uuid4().hex[:12]}{extension}"
        )
        server_temp: Path | None = None
        published_target: Path | None = None
        successful = False
        try:
            with open(local_part, "xb") as fp:
                fp.write(content)
                fp.flush()
                safe_fsync(fp, path=local_part)

            self._verify_download_file(local_part, len(content), extension, digest, "로컬 staging")

            retry_file_operation(
                lambda: target.parent.mkdir(parents=True, exist_ok=True),
                path=target.parent,
                operation_name="네트워크 최종 디렉터리 생성",
            )
            retry_file_operation(
                lambda: server_staging_dir.mkdir(parents=True, exist_ok=True),
                path=server_staging_dir,
                operation_name="네트워크 upload staging 디렉터리 생성",
            )
            server_temp = server_staging_dir / (
                f".upload_{normalize_storage_component(run_id)}_{uuid.uuid4().hex[:12]}{extension}"
            )

            def copy_once() -> None:
                safe_unlink(server_temp)
                with open(local_part, "rb") as source, open(server_temp, "xb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
                    destination.flush()
                    safe_fsync(destination, path=server_temp)

            retry_file_operation(
                copy_once,
                path=server_temp,
                operation_name="네트워크 임시 파일 복사",
            )
            self._verify_download_file(server_temp, len(content), extension, digest, "네트워크 임시 파일")

            # 수동 생성 파일을 덮어쓰지 않도록 존재 시 다음 이름으로 이동한다.
            for _ in range(100):
                if retry_file_operation(
                    lambda: strict_exists(target),
                    path=target,
                    operation_name="네트워크 대상 파일 확인",
                ):
                    target = self._next_available_path_with_retry(target)
                published_new_target = not retry_file_operation(
                    lambda: strict_exists(target),
                    path=target,
                    operation_name="네트워크 대상 파일 재확인",
                )
                try:
                    retry_file_operation(
                        lambda: os.rename(server_temp, target),
                        path=target,
                        operation_name="네트워크 최종 파일 반영",
                    )
                    server_temp = None
                    break
                except FileExistsError:
                    target = self._next_available_path_with_retry(target)
            else:
                raise OSError(f"파일명 충돌이 너무 많습니다: {target}")

            if published_new_target:
                published_target = target
            self._verify_download_file(target, len(content), extension, digest, "최종 파일")
            successful = True
            return target
        finally:
            if not successful and published_target is not None:
                try:
                    safe_unlink(published_target)
                except OSError:
                    self.log.warning("네트워크 최종 파일 정리 실패: %s", published_target)
            if server_temp is not None:
                try:
                    safe_unlink(server_temp)
                except OSError:
                    self.log.warning("네트워크 임시 파일 정리 실패: %s", server_temp)
            try:
                safe_unlink(local_part)
            except OSError:
                self.log.warning("로컬 staging 파일 정리 실패: %s", local_part)
            self._cleanup_empty_staging_dirs(staging_dir)
            self._cleanup_empty_staging_dirs(server_staging_dir)

    @staticmethod
    def _verify_download_file(
        path: Path,
        expected_size: int,
        extension: str,
        digest: str,
        label: str,
    ) -> None:
        """파일 검증/해시를 수행하고 실패 시 명확한 OSError를 낸다."""

        check = DownloadService._validate_saved_file_with_retry(
            path, expected_size, extension, label
        )
        if not check.ok:
            raise OSError(f"{label} 검증 실패: {check.reason}")
        actual_digest = retry_file_operation(
            lambda: sha256_file(path),
            path=path,
            operation_name=f"{label} SHA-256 계산",
        )
        if actual_digest != digest:
            raise OSError(f"{label} SHA-256 불일치")

    @staticmethod
    def _validate_saved_file_with_retry(
        path: Path,
        expected_size: int,
        extension: str,
        label: str,
    ):
        """네트워크 검증 중 일시적 open/stat 오류만 짧게 재시도한다."""

        def validate_once():
            result = validate_saved_file(path, expected_size, extension)
            if not result.ok and str(result.reason).startswith("파일을 열 수 없음"):
                raise OSError(result.reason)
            return result

        return retry_file_operation(
            validate_once,
            path=path,
            operation_name=f"{label} 검증",
        )

    def _next_available_path_with_retry(self, target: Path) -> Path:
        """네트워크 저장소에서 ``Path.exists``의 오류 삼킴 없이 충돌명을 계산한다."""

        stem = target.stem
        suffix = target.suffix
        candidate = target
        index = 2
        while retry_file_operation(
            lambda: strict_exists(candidate),
            path=candidate,
            operation_name="충돌 파일명 확인",
        ):
            candidate = target.with_name(f"{stem}_{index}{suffix}")
            index += 1
        return candidate

    @staticmethod
    def _cleanup_empty_staging_dirs(staging_dir: Path) -> None:
        """성공·실패 후 비어 있는 회사/run staging 디렉터리를 정리한다."""
        current = staging_dir
        for _ in range(2):
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    # ------------------------------------------------------------------
    def _previous_file_ok(self, previous: dict) -> bool:
        """체크포인트 유효성: 파일이 실제로 있고 해시가 일치하는지."""
        saved = previous.get("saved_relative_path") or ""
        if not saved:
            return False
        try:
            path = self.paths.resolve_relative_path(saved)
        except (TypeError, ValueError):
            return False
        try:
            exists = retry_file_operation(
                lambda: strict_exists(path),
                path=path,
                operation_name="체크포인트 파일 존재 확인",
            )
        except OSError:
            return False
        if not exists:
            return False
        expected = previous.get("sha256") or ""
        if not expected:
            return True
        try:
            return retry_file_operation(
                lambda: sha256_file(path),
                path=path,
                operation_name="체크포인트 파일 SHA-256 계산",
            ) == expected
        except OSError:
            return False

    def _set_saved_path(self, record: ManifestRecord, value: str | Path) -> None:
        """입력을 검증하고 출력 루트 기준 POSIX 상대경로 하나로 기록한다."""
        if not value:
            return
        raw = str(value)
        try:
            # Previous checkpoints already contain the canonical relative form.
            path = self.paths.resolve_relative_path(raw)
        except ValueError:
            path = Path(value)
        try:
            relative = self.paths.relative_output_path(path)
        except ValueError as exc:
            raise ValueError(f"출력 루트 밖의 저장 경로입니다: {path}") from exc
        # 영속 경로는 항상 출력 루트 기준 POSIX 상대경로 하나로 정본화한다.
        record.saved_relative_path = relative

    def _log_error(self, version: ProductVersion, document: Document, record: ManifestRecord) -> None:
        self.log.warning(
            "[%s] %s / %s -> %s (%s)",
            version.company_code,
            version.product_name_raw,
            document.document_label,
            record.download_status,
            record.error_message,
        )
        self.errors.record(
            company=version.company_code,
            product=version.product_name_raw,
            version=version.resolved_version_key(),
            document_type=document.document_type,
            label=document.document_label,
            url=document.document_url,
            status=record.download_status,
            error=record.error_message,
        )

    def _storage_failure(
        self,
        version: ProductVersion,
        document: Document,
        record: ManifestRecord,
        exc: OSError,
    ) -> ManifestRecord:
        """네트워크/로컬 파일 준비 오류를 문서 실패로 일관되게 기록한다."""
        record.download_status = DownloadStatus.DOWNLOAD_FAILED
        record.error_message = f"파일 저장 준비 실패: {exc}"
        self._log_error(version, document, record)
        return self._add(version, document, record)

    # ------------------------------------------------------------------
    def _base_record(self, version: ProductVersion, document: Document | None = None) -> ManifestRecord:
        record = ManifestRecord(
            company_code=version.company_code,
            company_name=version.company_name,
            product_category=version.product_category,
            product_name_raw=version.product_name_raw,
            product_name_normalized=normalize_storage_component(version.product_name_raw),
            source_product_id=version.source_product_id,
            sale_status=version.sale_status,
            normalized_sale_status=str(version.normalized_sale_status),
            source_sale_status=version.sale_status,
            status_source=str((version.extra or {}).get("status_source") or "collection"),
            status_check_result="COLLECTED",
            sale_start_date=fmt_date(version.sale_start_date),
            sale_end_date=fmt_date(version.sale_end_date),
            disclosure_date=fmt_date(version.disclosure_date),
            revision_date=fmt_date(version.revision_date),
            target_date=fmt_date(version.target_date),
            date_basis=version.date_basis,
            source_page_url=version.source_page_url,
            checkpoint_key=str((version.extra or {}).get("_plan_checkpoint_key") or ""),
        )
        if document is not None:
            record.document_type = document.document_type
            record.document_label = document.document_label
            record.document_url = document.document_url
            record.original_filename = document.original_filename
            from crawler.document_identity import source_locator_for_document
            record.source_locator = source_locator_for_document(document)
            record.has_download_target = document.has_link
        return record
