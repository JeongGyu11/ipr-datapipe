"""Collection use-case shared by the CLI and FastAPI scheduler.

The crawler manager remains responsible for company-level crawling, locks and
run-summary persistence.  This module owns the run-level lifecycle: request
validation, storage/DB preflight, the process advisory lock and exit mapping.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Literal

import psycopg
from yaml import YAMLError

from app.application.reporting import log_summary
from app.core.ipr_logger import get_logger, push_trace_id, reset_trace_id
from crawler.adapters import ADAPTER_REGISTRY
from crawler.company_catalog import (
    COMPANIES,
    CollectionStatus as CompanyCollectionStatus,
    validate_company_selection,
)
from crawler.config import AppConfig, load_config
from crawler.crawler_manager import CrawlerManager, RunOptions
from crawler.db_readiness import DBReadinessChecker, DBReadinessError
from crawler.document_repository import (
    DatabaseConfig,
    close_document_repository,
    open_document_repository,
)
from crawler.lock_service import force_unlock, list_locks
from crawler.path_service import NetworkPathError, PathService
from crawler.plan_service import PlanService
from crawler.run_context import RunContext
from utils.date_utils import date_range, month_range, period_scope_key


SCHEDULE_ADVISORY_LOCK_KEY = 6_184_320_271_991_517


class AdvisoryLockUnavailable(RuntimeError):
    """The shared PostgreSQL advisory lock is owned by another run."""


class PostgresAdvisoryLock(AbstractContextManager["PostgresAdvisoryLock"]):
    """Session-level advisory lock shared by CLI and scheduler executions."""

    def __init__(
        self,
        connect: Callable[[], Any],
        key: int = SCHEDULE_ADVISORY_LOCK_KEY,
    ) -> None:
        self._connect = connect
        self.key = int(key)
        self.connection: Any | None = None

    def __enter__(self) -> "PostgresAdvisoryLock":
        self.connection = self._connect()
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", (self.key,))
                row = cursor.fetchone()
            if not row or not bool(row[0]):
                raise AdvisoryLockUnavailable("collection is already running")
            return self
        except BaseException:
            self.connection.close()
            self.connection = None
            raise

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        connection, self.connection = self.connection, None
        if connection is None:
            return
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", (self.key,))
        finally:
            connection.close()


def _db_connect() -> Any:
    return psycopg.connect(**DatabaseConfig.from_env().connect_kwargs())


@dataclass(frozen=True)
class CollectionRequest:
    config_path: Path
    target_month: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    companies: tuple[str, ...] = ()
    dry_run: bool = False
    write_plan: bool = False
    download_plan: Path | None = None
    retry_failed: bool = False
    refresh_active: bool = True
    refresh_active_only: bool = False
    rename_dry_run: bool = False
    max_products: int | None = None
    max_versions: int | None = None
    verbose: bool = False

    def validate_shape(self) -> None:
        """DB·storage 접근 전에 transport 공통 실행 조건을 검증한다."""

        for option, value in (
            ("--max-products", self.max_products),
            ("--max-versions", self.max_versions),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"{option}는 1 이상의 정수여야 합니다")
        if self.end_date and not self.start_date:
            raise ValueError("--end-date는 --start-date와 함께 지정해야 합니다")
        if self.start_date and not self.end_date:
            raise ValueError("--start-date는 --end-date와 함께 지정해야 합니다")
        if self.target_month and (self.start_date or self.end_date):
            raise ValueError("--target-month와 --start-date/--end-date는 함께 사용할 수 없습니다")
        if self.target_month:
            month_range(self.target_month)
        elif self.start_date and self.end_date:
            date_range(self.start_date, self.end_date)
        if self.refresh_active_only and not self.refresh_active:
            raise ValueError("--refresh-active-only은 --no-refresh-active와 함께 사용할 수 없습니다")
        if self.rename_dry_run and not self.refresh_active:
            raise ValueError("--rename-dry-run은 --no-refresh-active와 함께 사용할 수 없습니다")
        if self.refresh_active_only and (
            self.write_plan or self.retry_failed or self.max_versions is not None
        ):
            raise ValueError(
                "--refresh-active-only은 --write-plan/--retry-failed/--max-versions와 함께 사용할 수 없습니다"
            )
        if self.download_plan is not None and any(
            (
                self.target_month,
                self.start_date,
                self.end_date,
                self.companies,
                self.write_plan,
                self.retry_failed,
                self.max_products is not None,
                self.max_versions is not None,
                not self.refresh_active,
                self.refresh_active_only,
                self.rename_dry_run,
            )
        ):
            raise ValueError(
                "--download-plan은 기간/보험사/수집 제한/--write-plan/--retry-failed와 함께 사용할 수 없습니다"
            )


CollectionRunStatus = Literal["SUCCESS", "FAILED", "LOCKED", "INVALID", "INFRA_ERROR", "SKIPPED"]


@dataclass(frozen=True)
class CollectionResult:
    exit_code: int
    status: CollectionRunStatus
    summary: dict[str, Any] | None = None
    run_id: str | None = None
    summary_path: Path | None = None
    error: str | None = None
    checks: dict[str, bool] | None = None


@dataclass(frozen=True)
class _ResolvedRequest:
    target_month: str | None
    period_start: date
    period_end: date
    scope_key: str
    selected_companies: tuple[str, ...]


class CollectionApplication:
    """Run-level collection use-case.

    All dependencies are injectable so scheduler/API tests never need a live
    database or file server.  The default advisory lock is deliberately here,
    rather than in a transport adapter, so manual CLI runs and scheduled runs
    share the same single-run boundary.
    """

    def __init__(
        self,
        *,
        config_loader: Callable[[str | Path], AppConfig] = load_config,
        path_factory: Callable[..., PathService] = PathService,
        context_factory: Callable[..., RunContext] = RunContext.create,
        manager_factory: Callable[..., CrawlerManager] = CrawlerManager,
        repository_factory: Callable[[], Any] | None = None,
        readiness_factory: Callable[..., DBReadinessChecker] = DBReadinessChecker,
        lock_factory: Callable[[], AbstractContextManager[Any]] | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.config_loader = config_loader
        self.path_factory = path_factory
        self.context_factory = context_factory
        self.manager_factory = manager_factory
        self.repository_factory = repository_factory
        self.readiness_factory = readiness_factory
        self.lock_factory = lock_factory or (lambda: PostgresAdvisoryLock(_db_connect))
        self.project_root = project_root or Path(__file__).resolve().parents[2]

    def run(self, request: CollectionRequest) -> CollectionResult:
        """Execute one collection while holding the shared advisory lock."""

        logger = get_logger(__name__)
        try:
            request.validate_shape()
            config = self.config_loader(request.config_path)
            resolved = self._resolve_request(request, config)
        except (FileNotFoundError, OSError, ValueError, YAMLError) as exc:
            logger.error("설정/실행 요청을 확인할 수 없습니다: %s", exc)
            return CollectionResult(2, "INVALID", error=str(exc))
        try:
            with self.lock_factory():
                return self._run_locked(request, config, resolved)
        except AdvisoryLockUnavailable:
            get_logger().info("수집을 건너뜁니다: 다른 실행이 PostgreSQL advisory lock을 보유 중입니다")
            return CollectionResult(4, "LOCKED", error="collection advisory lock unavailable")
        except (OSError, psycopg.Error) as exc:
            get_logger().error("공통 수집 advisory lock을 사용할 수 없습니다: %s", exc)
            return CollectionResult(3, "INFRA_ERROR", error=f"{type(exc).__name__}: {exc}")

    def validate_startup_environment(self, config_path: Path) -> CollectionResult:
        """Validate config, writable storage and DB contract once at startup.

        The same preflight primitives are reused by a collection run. This
        method intentionally does not acquire the collection-wide advisory
        lock; it only holds the DB readiness migration lock for its check.
        """

        logger = get_logger(__name__)
        checks: dict[str, bool] = {"storage": False, "database": False}
        repository = None
        readiness = None
        try:
            config = self.config_loader(config_path)
        except (FileNotFoundError, OSError, ValueError, YAMLError) as exc:
            logger.error("설정을 읽을 수 없습니다: %s", exc)
            return CollectionResult(2, "INVALID", error=str(exc), checks=checks)
        try:
            target_month = config.target_month
            scope_key = target_month or "config"
            paths = self._paths_for(config, target_month, scope_key)
            paths.verify_base_path()
            checks["storage"] = True
            repository = open_document_repository(self.repository_factory)
            codes = [
                company.code
                for company in COMPANIES
                if company.collection_status is CompanyCollectionStatus.ACTIVE
            ]
            readiness = self.readiness_factory(
                repository,
                outbox_dirs=[paths.db_outbox_path(code).parent for code in codes],
                outbox_paths=[paths.db_outbox_path(code) for code in codes],
            )
            result = readiness.ensure(hold_migration_lock=True)
            checks["database"] = True
            return CollectionResult(0, "SUCCESS", checks=checks)
        except NetworkPathError as exc:
            logger.error("%s", exc.format_message())
            return CollectionResult(3, "INFRA_ERROR", error=str(exc), checks=checks)
        except DBReadinessError as exc:
            detail = getattr(exc, "result", None)
            if detail is not None:
                checks["database"] = bool(getattr(detail, "ready", False))
            logger.error("%s", exc)
            return CollectionResult(3, "INFRA_ERROR", error=str(exc), checks=checks)
        except (FileNotFoundError, OSError, ValueError, RuntimeError, psycopg.Error, YAMLError) as exc:
            logger.error("%s", exc)
            return CollectionResult(3, "INFRA_ERROR", error=str(exc), checks=checks)
        finally:
            if readiness is not None:
                readiness.release_migration_lock()
            if repository is not None:
                close_document_repository(repository)

    def lock_status(self, config_path: Path, *, verbose: bool = False) -> CollectionResult:
        logger = get_logger(__name__)
        try:
            config = self.config_loader(config_path)
            paths = self._paths_for(config, config.target_month, config.target_month or "config")
            paths.verify_base_path()
            log_lock_status(paths, logger)
            return CollectionResult(0, "SUCCESS")
        except (FileNotFoundError, OSError, ValueError, YAMLError) as exc:
            logger.error("%s", exc)
            return CollectionResult(2, "INVALID", error=str(exc))
        except NetworkPathError as exc:
            logger.error("%s", exc.format_message())
            return CollectionResult(3, "INFRA_ERROR", error=str(exc))

    def force_unlock(
        self,
        config_path: Path,
        company_code: str,
        *,
        verbose: bool = False,
    ) -> CollectionResult:
        """Force-unlock only after acquiring the common global lock."""

        logger = get_logger(__name__)
        trace_token = None
        try:
            config = self.config_loader(config_path)
            code = company_code.strip().upper()
            if not code:
                raise ValueError("보험사 코드가 비어 있습니다")
            paths = self._paths_for(config, config.target_month, config.target_month or "config")
            paths.verify_base_path()
            context = self.context_factory(self.project_root)
            trace_token = push_trace_id(context.run_id)
            run_dir = paths.run_dir(context.run_id)
            with self.lock_factory():
                event = force_unlock(
                    paths.lock_path(code),
                    context=context,
                    audit_path=run_dir / "lock_audit.jsonl",
                    display_path=paths.relative_output_path(paths.lock_path(code)),
                )
            logger.info("잠금을 해제했습니다: %s", event["lock_path"])
            logger.info(
                "해제 프로세스: run_id=%s / PC=%s / PID=%s",
                context.run_id,
                context.computer_name,
                context.process_id,
            )
            return CollectionResult(0, "SUCCESS", run_id=context.run_id)
        except AdvisoryLockUnavailable:
            logger.error("강제 잠금을 거부했습니다: 다른 수집이 실행 중입니다")
            return CollectionResult(4, "LOCKED", error="collection advisory lock unavailable")
        except FileNotFoundError as exc:
            logger.error("%s", exc)
            return CollectionResult(2, "INVALID", error=str(exc))
        except NetworkPathError as exc:
            logger.error("%s", exc.format_message())
            return CollectionResult(3, "INFRA_ERROR", error=str(exc))
        except psycopg.Error as exc:
            logger.error("%s", exc)
            return CollectionResult(3, "INFRA_ERROR", error=str(exc))
        except OSError as exc:
            logger.error("%s", exc)
            return CollectionResult(3, "INFRA_ERROR", error=str(exc))
        except (ValueError, YAMLError) as exc:
            logger.error("%s", exc)
            return CollectionResult(2, "INVALID", error=str(exc))
        finally:
            if trace_token is not None:
                reset_trace_id(trace_token)

    def _run_locked(
        self,
        request: CollectionRequest,
        config: AppConfig,
        resolved: _ResolvedRequest,
    ) -> CollectionResult:
        logger = get_logger(__name__)
        try:
            paths = self._paths_for(config, resolved.target_month, resolved.scope_key)
            paths.verify_base_path()
        except NetworkPathError as exc:
            logger.error("%s", exc.format_message())
            return CollectionResult(3, "INFRA_ERROR", error=str(exc))
        except (FileNotFoundError, OSError, ValueError, RuntimeError) as exc:
            logger.error("%s", exc)
            return CollectionResult(2, "INVALID", error=str(exc))

        context = self.context_factory(self.project_root)
        trace_token = push_trace_id(context.run_id)
        try:
            return self._execute_collection_run(request, config, resolved, paths, context, logger)
        finally:
            reset_trace_id(trace_token)

    def _execute_collection_run(
        self,
        request: CollectionRequest,
        config: AppConfig,
        resolved: _ResolvedRequest,
        paths: PathService,
        context: RunContext,
        logger: Any,
    ) -> CollectionResult:
        """Execute a prepared collection while its run ID is in log context."""

        logger.info(
            "실행 프로세스: run_id=%s / PC=%s / PID=%s / 시작=%s / commit=%s",
            context.run_id,
            context.computer_name,
            context.process_id,
            context.started_at,
            context.git_commit or "알 수 없음",
        )
        if resolved.target_month:
            logger.info(
                "대상 월 %s (%s ~ %s)",
                resolved.target_month,
                resolved.period_start,
                resolved.period_end,
            )
        else:
            logger.info(
                "대상 기간 %s (%s ~ %s)",
                resolved.scope_key,
                resolved.period_start,
                resolved.period_end,
            )
        logger.info("저장 루트: %s", paths.output_root)

        options = self._run_options(request, resolved)
        readiness_checker = None
        readiness_repository = None
        manager = None
        try:
            manager = self.manager_factory(
                config,
                options,
                context=context,
                repository_factory=self.repository_factory,
                paths=paths,
            )
            selected_for_outbox = list(resolved.selected_companies) or [
                company.code
                for company in COMPANIES
                if company.collection_status is CompanyCollectionStatus.ACTIVE
            ]
            readiness_repository = open_document_repository(self.repository_factory)
            readiness_checker = self.readiness_factory(
                readiness_repository,
                outbox_dirs=[paths.db_outbox_path(code).parent for code in selected_for_outbox],
                outbox_paths=[paths.db_outbox_path(code) for code in selected_for_outbox],
            )
            readiness_result = readiness_checker.ensure(hold_migration_lock=True)
            manager.db_readiness = readiness_result.as_dict()
            summary = manager.run()
        except DBReadinessError as exc:
            logger.error("%s", exc)
            return CollectionResult(3, "INFRA_ERROR", run_id=context.run_id, error=str(exc))
        except ValueError as exc:
            logger.error("%s", exc)
            return CollectionResult(2, "INVALID", run_id=context.run_id, error=str(exc))
        except (OSError, RuntimeError) as exc:
            logger.error("%s", exc)
            return CollectionResult(3, "INFRA_ERROR", run_id=context.run_id, error=str(exc))
        finally:
            if readiness_checker is not None:
                readiness_checker.release_migration_lock()
            if readiness_repository is not None:
                close_document_repository(readiness_repository)

        log_summary(summary, logger)
        for code, plan_path in manager.plan_paths.items():
            logger.info("[%s] download plan: %s", code, plan_path)
        logger.info("summary : %s", manager.summary_path)
        failed = sum(
            count
            for status, count in (summary.get("status_counts") or {}).items()
            if status in ("DOWNLOAD_FAILED", "INVALID_RESPONSE", "INVALID_FILE", "ACCESS_DENIED")
        )
        if summary.get("locked_companies"):
            return CollectionResult(
                4,
                "LOCKED",
                summary=summary,
                run_id=context.run_id,
                summary_path=manager.summary_path,
            )
        company_failed = any(
            info.get("status") == "FAILED"
            for info in (summary.get("companies") or {}).values()
        )
        if failed or company_failed:
            status: CollectionRunStatus = "FAILED"
            exit_code = 1
        else:
            status = "SUCCESS"
            exit_code = 0
        return CollectionResult(
            exit_code,
            status,
            summary=summary,
            run_id=context.run_id,
            summary_path=manager.summary_path,
        )

    def _resolve_request(self, request: CollectionRequest, config: AppConfig) -> _ResolvedRequest:
        selected_companies = list(request.companies)
        if request.download_plan is not None:
            # lock 전 요청 검증은 영속 plan을 절대 복구/변경하지 않는다.
            plan_items = PlanService(request.download_plan, repair=False).items()
            if not plan_items:
                raise ValueError(f"다운로드 계획이 비어 있습니다: {request.download_plan}")
            if any(not item.company_code.strip() for item in plan_items):
                raise ValueError("다운로드 계획에 company_code가 비어 있는 항목이 있습니다")
            selected_companies = sorted({item.company_code.upper() for item in plan_items})
            if len(selected_companies) != 1:
                raise ValueError("--download-plan은 한 보험사의 계획 파일만 지원합니다")
            plan_dates = sorted(item.target_date for item in plan_items if item.target_date)
            if not plan_dates:
                raise ValueError("다운로드 계획에 유효한 target_date가 없습니다")
            period_start, period_end = date_range(plan_dates[0], plan_dates[-1])
            target_month = None
            scope_key = period_scope_key(period_start, period_end)
        else:
            if request.start_date:
                period_start, period_end = date_range(request.start_date, request.end_date)
                target_month = None
                scope_key = period_scope_key(period_start, period_end)
            else:
                target_month = request.target_month or config.target_month
                if not target_month:
                    raise ValueError(
                        "수집 기간이 없습니다. --target-month 또는 --start-date/--end-date를 지정하세요"
                    )
                period_start, period_end = month_range(target_month)
                scope_key = target_month

        selected_companies = list(
            validate_company_selection(selected_companies, ADAPTER_REGISTRY)
        )
        return _ResolvedRequest(
            target_month=target_month,
            period_start=period_start,
            period_end=period_end,
            scope_key=scope_key,
            selected_companies=tuple(selected_companies),
        )

    def _run_options(
        self, request: CollectionRequest, resolved: _ResolvedRequest
    ) -> RunOptions:
        return RunOptions(
            target_month=resolved.target_month,
            period_start=None if resolved.target_month else resolved.period_start,
            period_end=None if resolved.target_month else resolved.period_end,
            scope_key=resolved.scope_key,
            companies=list(resolved.selected_companies),
            dry_run=request.dry_run,
            retry_failed=request.retry_failed,
            max_products=request.max_products,
            max_versions=request.max_versions,
            write_plan=(request.write_plan or bool(request.start_date))
            and request.download_plan is None
            and not request.refresh_active_only,
            download_plan=str(request.download_plan) if request.download_plan else None,
            refresh_active=request.refresh_active,
            refresh_active_only=request.refresh_active_only,
            rename_dry_run=request.rename_dry_run,
        )

    def _paths_for(
        self, config: AppConfig, target_month: str | None, scope_key: str
    ) -> PathService:
        return self.path_factory(
            base_path=config.base_path,
            root_folder=config.root_folder,
            target_month=target_month or scope_key,
            max_path_length=config.max_path_length,
            scope_key=scope_key,
            storage_kind=config.storage_kind,
            local_staging_override=config.local_staging_path,
            local_state_override=config.local_state_path,
        )

def log_lock_status(paths: PathService, logger=None) -> None:
    logger = logger or get_logger()
    locks = list_locks(paths.locks_root)
    if not locks:
        logger.info("현재 보험사 실행 잠금이 없습니다.")
        return
    lines = ["현재 보험사 실행 잠금:"]
    for lock in locks:
        lines.append(f"- {lock.get('company_code', '?')} {lock.get('company_name', '')}")
        lines.append(f"  실행 ID: {lock.get('run_id', '알 수 없음')}")
        lines.append(f"  PC: {lock.get('computer_name', '알 수 없음')}")
        lines.append(f"  PID: {lock.get('process_id', '알 수 없음')}")
        lines.append(
            f"  수집 범위: {lock.get('scope_key', '알 수 없음')}"
        )
        if lock.get("period_start") or lock.get("period_end"):
            lines.append(
                f"  기간: {lock.get('period_start', '')} ~ {lock.get('period_end', '')}"
            )
        lines.append(f"  시작: {lock.get('started_at', '알 수 없음')}")
    logger.info("\n%s", "\n".join(lines))
