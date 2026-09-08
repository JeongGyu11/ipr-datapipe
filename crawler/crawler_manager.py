"""전체 실행 오케스트레이션."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from crawler.adapters import ADAPTER_REGISTRY
from crawler.config import AppConfig
from crawler.company_catalog import (
    COMPANIES,
    CollectionStatus,
    CompanyDefinition,
    get_company,
    validate_company_selection,
)
from crawler.db_outbox import DatabaseOutbox, validate_operation_event
from crawler.document_repository import (
    close_document_repository,
    open_document_repository,
)
from crawler.download_service import DownloadService
from crawler.http_client import AccessDeniedError
from crawler.lock_service import CompanyLock, LockHeldError
from crawler.manifest_service import ManifestRecord, ManifestService
from crawler.path_service import PathService
from crawler.plan_service import (
    PLAN_FILENAME,
    PLAN_MONTHS_DIRNAME,
    PLAN_STATE_FILENAME,
    PlanService,
)
from crawler.run_context import RunContext
from crawler.run_summary_service import RunSummaryWriter
from crawler.status_reconciliation_service import (
    RenameResult,
    RenameJournal,
    StatusFolderMover,
    StatusReconciliationService,
    active_manifest_rows,
    logical_version_key,
    observations_from_versions,
    replace_status_folder_path,
)
from crawler.validators import DocumentClassifier
from models.document import DocumentType, DownloadStatus
from models.product_version import ProductVersion
from utils.date_utils import date_range, month_range, period_scope_key, select_versions
from utils.crawler_logger import ErrorRecorder, get_logger
from utils.network_io import retry_file_operation, strict_exists


@dataclass
class RunOptions:
    target_month: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    scope_key: str | None = None
    companies: list[str] = field(default_factory=list)   # 비어 있으면 전체
    dry_run: bool = False
    retry_failed: bool = False
    max_products: int | None = None
    max_versions: int | None = None
    write_plan: bool = False
    download_plan: str | None = None
    refresh_active: bool = True
    refresh_active_only: bool = False
    rename_dry_run: bool = False


STATUS_REFRESH_COMPANIES = {
    "DB", "LOTTE", "SAMSUNG", "KB", "MERITZ", "MIRAE_LIFE", "KYOBO_LIFE", "DB_LIFE",
}


class CrawlerManager:
    def __init__(
        self,
        config: AppConfig,
        options: RunOptions,
        *,
        paths: PathService,
        context: RunContext | None = None,
        repository_factory=None,
    ):
        self.config = config
        self.options = options
        if options.refresh_active_only and not options.refresh_active:
            raise ValueError("refresh_active_only에는 refresh_active가 필요합니다")
        self.log = get_logger()
        self.context = context or RunContext.create()
        self.run_id = self.context.run_id
        if options.period_start is None and options.period_end is None:
            if not options.target_month:
                raise ValueError("target_month 또는 period_start/period_end가 필요합니다")
            self.period_start, self.period_end = month_range(options.target_month)
        elif options.period_start is None or options.period_end is None:
            raise ValueError("period_start와 period_end는 함께 지정해야 합니다")
        else:
            self.period_start, self.period_end = date_range(options.period_start, options.period_end)
        self.scope_key = options.scope_key or (
            options.target_month if options.target_month and options.period_start is None
            else period_scope_key(self.period_start, self.period_end)
        )
        # Application 계층에서 생성·검증한 동일 인스턴스를 전 실행에 사용한다.
        self.paths = paths
        self.classifier = DocumentClassifier(config.document_types, config.document_exclude_keywords)
        self.run_dir = self.paths.run_dir(self.run_id)
        self.summary_path = self.run_dir / "summary.json"
        self.errors = ErrorRecorder(self.run_dir / "errors.jsonl")
        self.plan_paths: dict[str, str] = {}
        self.repository_factory = repository_factory
        # CollectionApplication이 수집 시작 전에 채우는 runtime readiness 결과.
        self.db_readiness: dict | None = None

    def _open_repository(self):
        """공통 provider로 DB repository를 연다."""

        return open_document_repository(self.repository_factory)

    @staticmethod
    def _close_repository(repository) -> None:
        close_document_repository(repository)

    @staticmethod
    def _replay_db_outbox(repository, outbox: DatabaseOutbox) -> None:
        pending = outbox.pending()
        if not pending:
            # ACK 완료 이벤트만 누적된 outbox도 크기 임계값을 넘으면
            # 정리한다. 회사 lock을 보유한 replay 경계라 append와의
            # replace 경쟁 없이 원자 compact할 수 있다.
            outbox.compact_if_needed()
            return

        def apply(event: dict) -> None:
            validate_operation_event(event)
            operation = str(event.get("operation") or "")
            payload = event.get("payload") or {}
            if operation == "update_status_rows":
                result = repository.update_status_rows_detailed(payload)
                handled = int(result.handled)
                missing = int(result.missing)
                stale_noop = int(result.stale_noop)
                if stale_noop:
                    get_logger().info("DB outbox 판매상태 최신값 유지(stale no-op): %d건", stale_noop)
                if handled < len(payload) or missing:
                    actual = handled if handled >= 0 else "알 수 없음"
                    raise RuntimeError(
                        f"DB outbox 판매상태 갱신 누락: "
                        f"요청 {len(payload)}건, 반영/최신유지 {actual}건, 누락 {missing}건"
                    )
            elif operation == "upsert_seen":
                repository.upsert_seen(payload)
            elif operation == "upsert_result":
                repository.upsert_result(payload)
            else:  # validate_operation_event가 먼저 거부하지만 경계를 명시한다.
                raise RuntimeError(f"DB outbox 작업을 지원하지 않습니다: {operation}")

        result = outbox.replay(apply)
        if result["failed"]:
            raise RuntimeError(
                f"DB outbox 재생 실패: {result['failed']}건 (성공 {result['succeeded']}건)"
            )

    # ------------------------------------------------------------------
    def target_companies(self) -> list[CompanyDefinition]:
        # CollectionApplication을 우회해 Manager를 직접 호출해도 같은
        # catalog/adapter 계약과 명시 선택 정책을 적용한다.
        selected_codes = validate_company_selection(self.options.companies, ADAPTER_REGISTRY)
        wanted = set(selected_codes)
        result = []
        for company in COMPANIES:
            code = company.code.strip().upper()
            is_active = company.collection_status is CollectionStatus.ACTIVE
            if not is_active:
                continue
            if wanted and code not in wanted:
                continue
            result.append(company)
        return result

    # ------------------------------------------------------------------
    def run(self) -> dict:
        if self.options.download_plan:
            return self._run_download_plan()
        started = time.monotonic()

        summary = {
            "run_id": self.run_id,
            "computer_name": self.context.computer_name,
            "process_id": self.context.process_id,
            "git_commit": self.context.git_commit,
            "target_month": self.options.target_month,
            "scope_key": self.scope_key,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "period": {"start": self.period_start.isoformat(), "end": self.period_end.isoformat()},
            "date_selection_mode": self.config.date_selection_mode,
            "dry_run": self.options.dry_run,
            "retry_failed": self.options.retry_failed,
            "write_plan": self.options.write_plan,
            "refresh_active": self.options.refresh_active,
            "refresh_active_only": self.options.refresh_active_only,
            "rename_dry_run": self.options.rename_dry_run,
            "started_at": self.context.started_at,
            "layout_version": 3,
            "artifact_paths": self._relative_artifact_paths(),
            "db_readiness": self.db_readiness,
            "companies": {},
        }

        for company in self.target_companies():
            summary["companies"][company.code] = self._run_company(company)

        summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
        summary["elapsed_seconds"] = round(time.monotonic() - started, 1)
        total_counts: dict[str, int] = {}
        total_records = 0
        locked = []
        for code, info in summary["companies"].items():
            total_records += int(info.get("document_records", 0))
            if info.get("status") == "LOCKED":
                locked.append(code)
            for status, count in (info.get("status_counts") or {}).items():
                total_counts[status] = total_counts.get(status, 0) + int(count)
        summary["status_counts"] = total_counts
        summary["total_records"] = total_records
        summary["locked_companies"] = locked
        summary["plan_paths"] = dict(self.plan_paths)
        failed_companies = [
            code for code, info in summary["companies"].items()
            if info.get("status") == "FAILED"
        ]
        summary["failed_companies"] = failed_companies
        if failed_companies:
            summary["run_status"] = "FAILED"
        elif locked:
            summary["run_status"] = "PARTIAL_SUCCESS" if len(locked) < len(summary["companies"]) else "LOCKED"
        else:
            summary["run_status"] = "SUCCESS"

        RunSummaryWriter(self.summary_path).write(summary)
        return summary

    # ------------------------------------------------------------------
    def _run_company(self, company: CompanyDefinition) -> dict:
        adapter_class = ADAPTER_REGISTRY[company.code.upper()]
        runtime_options = dict(company.options)
        if self.options.max_products is not None:
            runtime_options["max_products"] = self.options.max_products

        adapter = adapter_class(
            company,
            self.config,
            self.classifier,
            runtime_options=runtime_options,
        )
        started = time.monotonic()
        info: dict = {
            "name": company.name,
            "url": company.entry_url,
            "collection_method": adapter_class.collection_method,
        }
        lock = CompanyLock(
            path=self.paths.lock_path(company.code),
            company_code=company.code,
            company_name=company.name,
            scope_key=self.scope_key,
            context=self.context,
            period_start=self.period_start.isoformat(),
            period_end=self.period_end.isoformat(),
        )
        status_mover: StatusFolderMover | None = None
        pending_status_moves: list[RenameResult] = []
        status_reconciliation_failed = False
        status_rows_committed = True
        repository = None
        outbox = None
        status_refresh_enabled = (
            self.options.refresh_active and company.code.upper() in STATUS_REFRESH_COMPANIES
        )
        active_rows: list[dict] = []
        try:
            lock.acquire()
        except LockHeldError as exc:
            owner = exc.owner
            owner_public = {key: value for key, value in owner.items() if key != "operator"}
            self.log.error(
                "[%s] 다른 프로세스가 실행 중입니다: run_id=%s, PC=%s, PID=%s, 시작=%s",
                company.code,
                owner.get("run_id", "알 수 없음"),
                owner.get("computer_name", "알 수 없음"),
                owner.get("process_id", "알 수 없음"),
                owner.get("started_at", "알 수 없음"),
            )
            info.update(
                status="LOCKED",
                error=f"LOCKED: {exc}",
                lock_owner=owner_public,
                elapsed_seconds=round(time.monotonic() - started, 1),
            )
            return info
        except OSError as exc:
            self.log.exception("[%s] 실행 잠금 생성 실패: %s", company.code, exc)
            info.update(
                status="FAILED",
                error=f"LOCK_CREATE_FAILED: {type(exc).__name__}: {exc}",
                elapsed_seconds=round(time.monotonic() - started, 1),
            )
            return info

        try:
            if hasattr(adapter, "configure_detail_checkpoint"):
                checkpoint_filename = getattr(
                    adapter, "detail_checkpoint_filename", "detail_checkpoint.v2.jsonl"
                )
                adapter.configure_detail_checkpoint(
                    str(
                        self.paths.checkpoint_path(
                            self.scope_key, company.code, checkpoint_filename
                        )
                    ),
                    scope=self.scope_key,
                )
            repository = self._open_repository()
            outbox = DatabaseOutbox(self.paths.db_outbox_path(company.code))
            self._replay_db_outbox(repository, outbox)
            manifest = ManifestService(
                output_root=self.paths.output_root,
                run_id=self.run_id,
                audit_event_path=self.paths.run_journal_path(self.run_id, company.code),
                outbox=outbox,
                repository=repository,
            )
            manifest.load_previous(company_code=company.code)
            company_manifest_rows = manifest.previous_rows_for_company(company.code)
            if company.code.upper() in STATUS_REFRESH_COMPANIES:
                status_mover = StatusFolderMover(
                    RenameJournal(
                        self.paths.status_move_journal_path(company.code),
                        output_root=self.paths.output_root,
                    ),
                    documents_root=self.paths.documents_root,
                )
                # dry-run/rename-dry-run은 문서 파일과 상태 폴더를 바꾸지 않는다.
                # 실행 로그·DB 상태·체크포인트 등 운영 산출물은 기록될 수 있다.
                if not self.options.dry_run and not self.options.rename_dry_run:
                    recovered = status_mover.recover()
                    recovered_rows, recovered_moves, recovery_stats = self._apply_recovered_status_moves(
                        company_manifest_rows, recovered
                    )
                    info.update(recovery_stats)
                    if any(
                        int(recovery_stats.get(key, 0))
                        for key in (
                            "active_status_recovery_conflicts",
                            "active_status_recovery_pending",
                            "active_status_recovery_unmatched",
                        )
                    ):
                        status_reconciliation_failed = True
                    if recovered_moves:
                        try:
                            manifest.replace_previous_rows(
                                self._changed_manifest_rows(company_manifest_rows, recovered_rows)
                            )
                        except Exception:
                            status_rows_committed = False
                            raise
                        pending_status_moves.extend(recovered_moves)
                        company_manifest_rows = recovered_rows
                if status_refresh_enabled:
                    active_rows = active_manifest_rows(company_manifest_rows, company.code)
                    if active_rows:
                        configure_refresh = getattr(adapter, "configure_active_status_refresh", None)
                        if not callable(configure_refresh):
                            raise RuntimeError(
                                f"{company.code} Adapter가 판매상태 재검증 계약을 구현하지 않았습니다"
                            )
                        configure_refresh(active_rows)
            info["active_status_candidates"] = len(active_rows)
            plan_service = None
            if self.options.write_plan:
                state_dir = self.paths.state_dir(self.scope_key, company.code)
                plan_path = state_dir / PLAN_FILENAME
                plan_service = PlanService(
                    plan_path,
                    state_path=state_dir / PLAN_STATE_FILENAME,
                )
                self.plan_paths[company.code] = self.paths.relative_output_path(plan_path)
            downloader = DownloadService(
                config=self.config,
                paths=self.paths,
                manifest=manifest,
                errors=self.errors,
                dry_run=self.options.dry_run,
                retry_failed_only=self.options.retry_failed,
                plan_service=plan_service,
                outbox=outbox,
            )
        except Exception as exc:  # noqa: BLE001 - 초기화 실패 시 반드시 잠금을 해제한다.
            self.log.exception("[%s] 실행 상태 초기화 실패: %s", company.code, exc)
            try:
                self._close_repository(repository)
            except Exception:
                self.log.exception("[%s] 초기화 실패 후 DB 연결 종료도 실패했습니다", company.code)
            release_error = ""
            try:
                lock.release()
            except OSError as release_exc:
                release_error = f"; LOCK_RELEASE_FAILED: {type(release_exc).__name__}: {release_exc}"
                self.log.exception("[%s] 초기화 실패 후 잠금 해제도 실패했습니다: %s", company.code, release_exc)
            info.update(
                status="FAILED",
                error=f"INITIALIZATION_FAILED: {type(exc).__name__}: {exc}{release_error}",
                elapsed_seconds=round(time.monotonic() - started, 1),
            )
            return info
        orphan_parts = []
        local_staging_exists = retry_file_operation(
            lambda: strict_exists(self.paths.local_staging_root),
            path=self.paths.local_staging_root,
            operation_name="로컬 staging 루트 확인",
        )
        if local_staging_exists:
            orphan_parts = sorted(
                retry_file_operation(
                    lambda: list(self.paths.local_staging_root.glob(
                        f"*/{company.code.upper()}/.part_*"
                    )),
                    path=self.paths.local_staging_root,
                    operation_name="로컬 staging 임시 파일 탐색",
                )
            )
        info["orphan_part_file_count"] = len(orphan_parts)
        if orphan_parts:
            self.log.warning(
                "[%s] 이전 비정상 종료로 추정되는 part 파일 %d건이 있습니다. 자동 삭제하지 않습니다.",
                company.code,
                len(orphan_parts),
            )
        try:
            orphan_uploads = sorted(
                retry_file_operation(
                    lambda: list(self.paths.staging_root.glob(
                        f"*/{company.code.upper()}/.upload_*"
                    )),
                    path=self.paths.staging_root,
                    operation_name="네트워크 upload 임시 파일 탐색",
                )
            )
        except OSError as exc:
            orphan_uploads = []
            self.log.warning("[%s] 네트워크 upload 임시 파일 탐색 실패: %s", company.code, exc)
        info["orphan_upload_file_count"] = len(orphan_uploads)
        if orphan_uploads:
            self.log.warning(
                "[%s] 이전 비정상 종료로 추정되는 네트워크 upload 임시 파일 %d건이 있습니다. "
                "자동 삭제하지 않습니다.",
                company.code,
                len(orphan_uploads),
            )
        self.log.info("=" * 72)
        self.log.info("[%s] %s 수집 시작 (%s ~ %s)", company.code, company.name,
                      self.period_start, self.period_end)

        try:
            with adapter:
                if self.options.refresh_active_only and not active_rows:
                    collected = []
                    adapter.stats["status_coverage_complete"] = True
                else:
                    collected = adapter.collect_product_versions(self.period_start, self.period_end)

                if status_refresh_enabled and active_rows:
                    coverage_complete = bool(adapter.stats.get("status_coverage_complete", False))
                    observed_at = datetime.now().isoformat(timespec="seconds")
                    observations = observations_from_versions(
                        active_rows,
                        collected,
                        coverage_complete=coverage_complete,
                        observed_at=observed_at,
                        source=f"{company.code}.collection",
                    )
                    reconciliation = StatusReconciliationService(dry_run=self.options.dry_run).reconcile(
                        company_manifest_rows,
                        observations,
                        company_coverage={company.code: coverage_complete},
                        observed_at=observed_at,
                    )
                    info["active_status_coverage_complete"] = coverage_complete
                    info["active_status_observed"] = len(observations)
                    info.update({
                        f"active_status_{key}": value
                        for key, value in reconciliation.stats.items()
                    })

                    outcomes: dict[str, RenameResult | bool] = {}
                    move_stats = {"moved": 0, "conflicts": 0, "failed": 0, "previewed": 0}
                    for action in reconciliation.actions:
                        if not action.move_required:
                            continue
                        if self.options.dry_run or self.options.rename_dry_run:
                            move_stats["previewed"] += 1
                            outcomes[action.key] = False
                            continue
                        if status_mover is None:
                            move_stats["failed"] += 1
                            outcomes[action.key] = False
                            continue
                        source_path = self._absolute_status_path(action.old_path)
                        destination_path = self._absolute_status_path(action.new_path)
                        outcome = status_mover.move(
                            source_path,
                            destination_path,
                            logical_key=action.key,
                            old_state=action.old_state,
                            new_state=action.new_state,
                        )
                        outcomes[action.key] = outcome
                        if outcome.phase == "MOVED":
                            move_stats["moved"] += 1
                            pending_status_moves.append(outcome)
                        elif outcome.conflict or outcome.phase == "CONFLICT":
                            move_stats["conflicts"] += 1
                            status_reconciliation_failed = True
                        else:
                            move_stats["failed"] += 1
                            status_reconciliation_failed = True

                    info.update({f"active_status_folder_{key}": value for key, value in move_stats.items()})
                    if not self.options.dry_run:
                        committed_rows = reconciliation.commit_actions(outcomes)
                        try:
                            manifest.replace_previous_rows(
                                self._changed_manifest_rows(company_manifest_rows, committed_rows)
                            )
                        except Exception:
                            status_rows_committed = False
                            status_reconciliation_failed = True
                            raise

                selected = [] if self.options.refresh_active_only else select_versions(
                    collected, self.period_start, self.period_end, self.config.date_selection_mode
                )
                raw_rows = adapter.stats.get("raw_rows")
                collected_count = (
                    int(raw_rows)
                    if isinstance(raw_rows, (int, float)) and int(raw_rows) >= len(collected)
                    else len(collected)
                )
                if collected_count != len(collected):
                    self.log.info(
                        "[%s] 원본 %d건 -> 객체 생성 후보 %d건 -> 기간 선정 %d건",
                        company.code, collected_count, len(collected), len(selected),
                    )
                else:
                    self.log.info(
                        "[%s] 수집 %d건 -> 기간 선정 %d건",
                        company.code, len(collected), len(selected),
                    )
                # 목록 단계에서 기간 후보만 ProductVersion으로 만드는 어댑터도
                # 기존 summary의 collected_versions 의미(원본 고유 행 수)를
                # 유지한다. 실제 객체 수는 materialized_rows 통계로 구분한다.
                info["collected_versions"] = collected_count
                info["selected_versions"] = len(selected)

                processed = selected
                if self.options.max_versions is not None and len(selected) > self.options.max_versions:
                    processed = selected[: self.options.max_versions]
                    self.log.warning(
                        "[%s] --max-versions=%d 적용: 대상 %d건 중 %d건만 처리합니다 (coverage_capped).",
                        company.code, self.options.max_versions, len(selected), len(processed),
                    )
                    info["coverage_capped"] = True
                    info["versions_total"] = len(selected)
                    info["versions_skipped"] = len(selected) - len(processed)

                info.update(self._process(downloader, adapter, processed))
                if plan_service is not None:
                    monthly = plan_service.create_monthly_index(
                        plan_service.plan_path.parent / PLAN_MONTHS_DIRNAME
                    )
                    info["download_plan"] = self.paths.relative_output_path(plan_service.plan_path)
                    info["planned_documents"] = len(plan_service.items())
                    info["planned_months"] = {month: len(keys) for month, keys in monthly.items()}
                info["processed_versions"] = len(processed)
                info["products"] = self._count_products(selected)
                info.update({k: v for k, v in adapter.stats.items()})
                retryable_count = self._retryable_count(info.get("status_counts") or {})
                if status_reconciliation_failed:
                    info["status"] = "FAILED"
                    info["error"] = "판매상태 폴더 이동 충돌 또는 실패"
                elif retryable_count:
                    info["status"] = "FAILED"
                    info["error"] = f"재시도 필요한 문서 {retryable_count}건"
                else:
                    info["status"] = "SUCCESS"
        except AccessDeniedError as exc:
            self.log.error("[%s] 접근 거부: %s", company.code, exc)
            self._record_company_status(manifest, company, DownloadStatus.ACCESS_DENIED, str(exc))
            info["error"] = f"ACCESS_DENIED: {exc}"
            info["status"] = "FAILED"
        except Exception as exc:  # noqa: BLE001 - 회사 단위 실패가 전체를 멈추지 않도록
            self.log.exception("[%s] 수집 중 오류: %s", company.code, exc)
            self._record_company_status(
                manifest, company, DownloadStatus.DOWNLOAD_FAILED, f"{type(exc).__name__}: {exc}"
            )
            info["error"] = f"{type(exc).__name__}: {exc}"
            info["status"] = "FAILED"
        finally:
            try:
                if status_mover is not None and status_rows_committed:
                    finalize_failed = 0
                    for move in pending_status_moves:
                        if not status_mover.finalize(move):
                            finalize_failed += 1
                    if finalize_failed:
                        info["active_status_finalize_failed"] = finalize_failed
                        info["error"] = f"STATUS_MOVE_FINALIZE_FAILED: {finalize_failed}건"
                        info["status"] = "FAILED"
            except Exception as exc:  # noqa: BLE001 - 잠금 해제 전에 이동 확정 실패를 결과에 반영
                self.log.exception("[%s] 상태 폴더 이동 확정 실패: %s", company.code, exc)
                info["error"] = f"STATUS_MOVE_FINALIZE_FAILED: {type(exc).__name__}: {exc}"
                info["status"] = "FAILED"
            finally:
                try:
                    self._close_repository(repository)
                except Exception as exc:  # noqa: BLE001
                    self.log.exception("[%s] DB 연결 종료 실패: %s", company.code, exc)
                    info["error"] = f"DB_CLOSE_FAILED: {type(exc).__name__}: {exc}"
                    info["status"] = "FAILED"
                try:
                    lock.release()
                except OSError as exc:
                    self.log.exception("[%s] 실행 잠금 해제 실패: %s", company.code, exc)
                    info["error"] = f"LOCK_RELEASE_FAILED: {type(exc).__name__}: {exc}"
                    info["status"] = "FAILED"

        info["status_counts"] = manifest.status_counts()
        info["document_records"] = len(manifest.records)
        info["elapsed_seconds"] = round(time.monotonic() - started, 1)
        return info

    # ------------------------------------------------------------------
    def _run_download_plan(self) -> dict:
        """저장된 plan만 사용해 사이트 목록/상세 재수집 없이 다운로드한다."""
        started = time.monotonic()
        selected_codes = validate_company_selection(self.options.companies, ADAPTER_REGISTRY)
        if len(selected_codes) != 1:
            raise ValueError("--download-plan 실행에는 검증된 보험사 코드 하나가 필요합니다")
        company_code = selected_codes[0]
        company = get_company(company_code)
        plan_path = Path(self.options.download_plan or "")

        adapter_class = ADAPTER_REGISTRY[company_code]
        adapter = adapter_class(
            company,
            self.config,
            self.classifier,
            runtime_options=dict(company.options),
        )
        lock = CompanyLock(
            path=self.paths.lock_path(company.code),
            company_code=company.code,
            company_name=company.name,
            scope_key=self.scope_key,
            context=self.context,
            period_start=self.period_start.isoformat(),
            period_end=self.period_end.isoformat(),
        )
        info: dict = {
            "name": company.name,
            "url": company.entry_url,
            "status": "FAILED",
            "download_plan": self.paths.relative_output_path(plan_path),
        }
        manifest = None
        repository = None
        outbox = None
        try:
            lock.acquire()
        except LockHeldError as exc:
            owner_public = {key: value for key, value in exc.owner.items() if key != "operator"}
            info.update(status="LOCKED", error=f"LOCKED: {exc}", lock_owner=owner_public)
            return self._finish_download_plan_summary(plan_path, company, info, started)
        except OSError as exc:
            info["error"] = f"LOCK_CREATE_FAILED: {type(exc).__name__}: {exc}"
            return self._finish_download_plan_summary(plan_path, company, info, started)

        try:
            # PlanService의 torn-tail/개행 복구는 회사 lock을 보유한 동안에만
            # 수행한다. Application이 lock 전에 수행한 검증은 read-only다.
            plan = PlanService(plan_path)
            items = plan.items()
            if not items:
                raise ValueError(f"다운로드 계획이 비어 있습니다: {plan.plan_path}")
            if any(not item.company_code.strip() for item in items):
                raise ValueError("다운로드 계획에 company_code가 비어 있는 항목이 있습니다")
            company_codes = {item.company_code.upper() for item in items}
            if company_codes != {company_code}:
                raise ValueError("다운로드 계획의 보험사 코드가 검증된 실행 요청과 다릅니다")
            info["planned_documents"] = len(items)
            repository = self._open_repository()
            outbox = DatabaseOutbox(self.paths.db_outbox_path(company.code))
            self._replay_db_outbox(repository, outbox)
            manifest = ManifestService(
                output_root=self.paths.output_root,
                run_id=self.run_id,
                audit_event_path=self.paths.run_journal_path(self.run_id, company.code),
                outbox=outbox,
                repository=repository,
            )
            manifest.load_previous(company_code=company.code)
            downloader = DownloadService(
                config=self.config,
                paths=self.paths,
                manifest=manifest,
                errors=self.errors,
                dry_run=self.options.dry_run,
                retry_failed_only=False,
                outbox=outbox,
            )
            with adapter:
                records = downloader.process_plan(adapter, plan)
            status_counts = manifest.status_counts()
            # process_plan 시작 시에는 pending_items()가 성공 파일 유실을
            # 확인한다. 종료 시에는 방금 갱신한 최신 state만으로 남은 수를
            # 계산해 같은 네트워크 경로를 다시 stat하지 않는다.
            remaining = plan.pending_count(verify_files=False)
            retryable_count = self._retryable_count(status_counts)
            plan_failed = not self.options.dry_run and (retryable_count > 0 or remaining > 0)
            info.update(
                status="FAILED" if plan_failed else "SUCCESS",
                document_records=len(records),
                status_counts=status_counts,
                remaining_documents=remaining,
            )
            if plan_failed:
                info["error"] = (
                    f"다운로드 plan 미완료: 재시도 필요 {retryable_count}건, "
                    f"남은 문서 {remaining}건"
                )
        except Exception as exc:
            info["error"] = f"{type(exc).__name__}: {exc}"
            self.log.exception("[%s] plan 다운로드 실패: %s", company.code, exc)
        finally:
            try:
                self._close_repository(repository)
            except Exception as exc:
                info["error"] = f"DB_CLOSE_FAILED: {type(exc).__name__}: {exc}"
                info["status"] = "FAILED"
                self.log.exception("[%s] plan DB 연결 종료 실패: %s", company.code, exc)
            finally:
                try:
                    lock.release()
                except OSError as exc:
                    info["error"] = f"LOCK_RELEASE_FAILED: {type(exc).__name__}: {exc}"
                    info["status"] = "FAILED"
        return self._finish_download_plan_summary(plan_path, company, info, started)

    def _finish_download_plan_summary(
        self, plan_path: Path, company: CompanyDefinition, info: dict, started: float
    ) -> dict:
        """plan 실행의 성공·실패·잠금 결과를 동일한 summary 형식으로 기록한다."""
        info["elapsed_seconds"] = round(time.monotonic() - started, 1)
        locked = [company.code] if info.get("status") == "LOCKED" else []
        failed = [company.code] if info.get("status") == "FAILED" else []
        summary = {
            "run_id": self.run_id,
            "computer_name": self.context.computer_name,
            "process_id": self.context.process_id,
            "git_commit": self.context.git_commit,
            "target_month": self.options.target_month,
            "scope_key": self.scope_key,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "period": {"start": self.period_start.isoformat(), "end": self.period_end.isoformat()},
            "date_selection_mode": self.config.date_selection_mode,
            "dry_run": self.options.dry_run,
            "retry_failed": False,
            "download_plan": self.paths.relative_output_path(plan_path),
            "started_at": self.context.started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "layout_version": 3,
            "artifact_paths": self._relative_artifact_paths(),
            "db_readiness": self.db_readiness,
            "companies": {company.code: info},
            "status_counts": info.get("status_counts", {}),
            "total_records": info.get("document_records", 0),
            "locked_companies": locked,
            "failed_companies": failed,
            "run_status": info.get("status", "FAILED"),
            "plan_paths": {company.code: self.paths.relative_output_path(plan_path)},
        }
        RunSummaryWriter(self.summary_path).write(summary)
        return summary

    # ------------------------------------------------------------------
    def _absolute_status_path(self, value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.paths.output_root / path

    def _relative_artifact_paths(self) -> dict[str, str]:
        return {
            "documents": self.paths.relative_output_path(self.paths.documents_root),
            "operations": self.paths.relative_output_path(self.paths.operations_root),
            "run": self.paths.relative_output_path(self.run_dir),
        }

    @staticmethod
    def _changed_manifest_rows(original: list[dict], updated: list[dict]) -> list[dict]:
        """상태 확인으로 실제 변경된 DB checkpoint 행만 고른다."""

        return [
            dict(after)
            for before, after in zip(original, updated, strict=False)
            if dict(before) != dict(after)
        ]

    @staticmethod
    def _apply_recovered_status_moves(
        rows: list[dict], recovered: list[RenameResult]
    ) -> tuple[list[dict], list[RenameResult], dict[str, int]]:
        """MOVED 저널을 DB checkpoint 행에 재적용하고 finalize 대상을 반환한다."""

        updated = [dict(row) for row in rows]
        matched_moves: list[RenameResult] = []
        stats = {
            "active_status_recovery_moved": 0,
            "active_status_recovery_conflicts": 0,
            "active_status_recovery_pending": 0,
            "active_status_recovery_unmatched": 0,
        }
        now = datetime.now().isoformat(timespec="seconds")
        for move in recovered:
            if move.phase == "CONFLICT" or move.conflict:
                stats["active_status_recovery_conflicts"] += 1
                continue
            if move.phase != "MOVED":
                stats["active_status_recovery_pending"] += 1
                continue
            indexes = [
                index
                for index, row in enumerate(updated)
                if logical_version_key(row) == move.logical_key
            ]
            if not indexes:
                stats["active_status_recovery_unmatched"] += 1
                continue
            for index in indexes:
                row = updated[index]
                field_name = "saved_relative_path"
                if row.get(field_name):
                    row[field_name] = replace_status_folder_path(
                        str(row[field_name]), move.source, move.destination
                    )
                if move.new_state:
                    row["normalized_sale_status"] = move.new_state
                row["status_check_result"] = "RECOVERED_MOVE"
                row["status_checked_at"] = now
                row["status_changed_at"] = row.get("status_changed_at") or now
            matched_moves.append(move)
            stats["active_status_recovery_moved"] += 1
        return updated, matched_moves, stats

    # ------------------------------------------------------------------
    def _process(self, downloader: DownloadService, adapter, versions: list[ProductVersion]) -> dict:
        records: list[ManifestRecord] = []
        for index, version in enumerate(versions, start=1):
            if index % 25 == 0:
                self.log.info("  진행 %d/%d", index, len(versions))
            records.extend(downloader.process_version(adapter, version))

        counts: dict[str, int] = {}
        doc_types: dict[str, int] = {}
        for record in records:
            counts[record.download_status] = counts.get(record.download_status, 0) + 1
            if record.document_type:
                doc_types[record.document_type] = doc_types.get(record.document_type, 0) + 1

        result = {
            "document_records": len(records),
            "document_links": self._count_document_links(records),
            "status_counts": counts,
            "document_type_counts": doc_types,
            "missing_documents": self._count_missing(versions),
        }
        if self.options.dry_run:
            samples: list[str] = []
            for record in records[:5]:
                if not record.saved_relative_path:
                    continue
                try:
                    # ManifestRecord stores a layout-relative POSIX path.
                    samples.append(str(record.saved_relative_path).replace("\\", "/"))
                except ValueError:
                    continue
            result["sample_paths"] = samples
        return result

    @staticmethod
    def _count_document_links(records: list[ManifestRecord]) -> int:
        """URL 또는 Adapter 전용 download_hint 가 있는 문서 수."""
        return sum(1 for record in records if record.has_download_target)

    @staticmethod
    def _count_missing(versions: list[ProductVersion]) -> dict[str, int]:
        """대상 3종 문서 중 링크가 없는 건수."""
        missing = {document_type: 0 for document_type in DocumentType.ALL_COLLECTED}
        for version in versions:
            present = {d.document_type for d in version.documents if d.has_link}
            for doc_type in missing:
                if doc_type not in present:
                    missing[doc_type] += 1
        return missing

    @staticmethod
    def _count_products(versions: list[ProductVersion]) -> int:
        """회사·상품명·원본 상품 ID의 논리 key로 상품 수를 집계한다."""

        return len(
            {
                (version.company_code, version.product_name_raw, version.source_product_id)
                for version in versions
            }
        )

    def _record_company_status(
        self,
        manifest: ManifestService,
        company: CompanyDefinition,
        status: str,
        message: str,
    ) -> None:
        record = ManifestRecord(
            company_code=company.code,
            company_name=company.name,
            source_page_url=company.entry_url,
            download_status=status,
            error_message=message,
        )
        manifest.add(record)
        self.errors.record(company=company.code, status=status, error=message)

    @staticmethod
    def _retryable_count(status_counts: dict[str, int]) -> int:
        """회사/plan 결과 중 실제 재시도가 필요한 문서 수."""
        return sum(
            int(count)
            for status, count in status_counts.items()
            if status in DownloadStatus.RETRYABLE
        )
