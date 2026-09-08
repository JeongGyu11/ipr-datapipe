"""PostgreSQL 문서 상태 저장소.

문서마다 짧은 트랜잭션으로 UPSERT한다.  manifest 스냅샷을 메모리에
유지하지 않으며, ``last_attempt_at``과 ``status_checked_at``을 비교해
늦게 도착한 이전 실행이 최신 상태를 덮지 못하게 한다.
"""

from __future__ import annotations

import re
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb

from crawler.document_identity import IDENTITY_VERSION, identity_for, metadata_for
from models.document import Document, DownloadStatus
from models.product_version import ProductVersion
from app.core.settings import SettingsError, get_settings

TABLE_NAME = "rs_disclosure_documents"
LEGACY_LOCAL_TIMEZONE = ZoneInfo("Asia/Seoul")
_DOCUMENT_KEY_RE = re.compile(r"^DOC_[0-9A-Za-z]{10}$")
_PRODUCT_VERSION_KEY_RE = re.compile(r"^PROD_VER_[0-9A-Za-z]{10}$")
_SOURCE_METADATA_IDENTITY_KEYS = frozenset(
    {"document_key", "product_version_key", "identity_version"}
)


class IdentityKeyCollisionError(ValueError):
    """동일 key가 서로 다른 논리 문서를 가리킬 때 발생하는 오류."""


@dataclass(frozen=True, repr=False)
class DatabaseConfig:
    host: str | None
    port: int | None
    user: str | None
    password: str | None
    dbname: str | None
    connect_timeout: int = 10
    sslmode: str | None = None

    def __repr__(self) -> str:
        return ("DatabaseConfig(host={!r}, port={!r}, user={!r}, password={!r}, dbname={!r}, "
                "connect_timeout={!r}, sslmode={!r})").format(
                    self.host, self.port, self.user, "***" if self.password else None,
                    self.dbname, self.connect_timeout, self.sslmode)

    @classmethod
    def from_env(
        cls,
        env_file: str | Path | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "DatabaseConfig":
        settings = get_settings(env_file=env_file, environ=environ).database
        return cls(settings.host, settings.port, settings.user, settings.password,
                   settings.dbname, settings.connect_timeout, settings.sslmode)

    def connect_kwargs(self) -> dict[str, Any]:
        required = {
            "RS_DB_HOST": self.host,
            "RS_DB_PORT": self.port,
            "RS_DB_USER": self.user,
            "RS_DB_PASSWORD": self.password,
            "RS_DB_NAME": self.dbname,
        }
        missing = [name for name, value in required.items() if value is None or not str(value).strip()]
        if missing:
            raise SettingsError("DB 설정이 비어 있습니다: " + ", ".join(missing))
        result = asdict(self)
        if result["sslmode"] is None:
            result.pop("sslmode")
        # 조회 후 장시간 열린 transaction을 남기지 않고, 각 upsert가
        # 명시적인 짧은 transaction으로 commit되도록 한다.
        result["autocommit"] = True
        return result


@dataclass
class DocumentPayload:
    """repository가 받는 최소 정규화 payload.

    dict도 허용하므로 마이그레이션 스크립트에서 직접 전달할 수 있다.
    """

    document_key: str
    product_version_key: str
    company_code: str
    company_name: str
    product_name: str
    product_name_normalized: str
    document_type: str | None = None
    document_label: str | None = None
    source_product_id: str | None = None
    product_category: str | None = None
    sale_status: str = "UNKNOWN"
    sale_status_raw: str | None = None
    sale_start_date: date | None = None
    sale_end_date: date | None = None
    status_checked_at: datetime | None = None
    status_changed_at: datetime | None = None
    status_missing_count: int = 0
    document_date: date | None = None
    document_date_basis: str | None = None
    source_page_url: str | None = None
    document_url: str | None = None
    original_filename: str | None = None
    source_metadata: dict[str, Any] | None = None
    saved_relative_path: str | None = None
    file_size: int | None = None
    sha256: str | None = None
    file_status: str = "PENDING"
    last_attempt_status: str | None = None
    error_message: str | None = None
    downloaded_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_seen_run_id: str | None = None
    last_download_run_id: str | None = None
    last_status_run_id: str | None = None
    last_seen_at: datetime | None = None
    collector_type: str = "PYTHON"
    identity_version: int = IDENTITY_VERSION


@dataclass(frozen=True)
class StatusUpdateResult:
    requested: int
    updated: int
    stale_noop: int
    missing: int

    @property
    def handled(self) -> int:
        return self.updated + self.stale_noop


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
        return (
            parsed.astimezone(timezone.utc)
            if parsed.tzinfo
            else parsed.replace(tzinfo=LEGACY_LOCAL_TIMEZONE).astimezone(timezone.utc)
        )
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return (
            parsed.astimezone(timezone.utc)
            if parsed.tzinfo
            else parsed.replace(tzinfo=LEGACY_LOCAL_TIMEZONE).astimezone(timezone.utc)
        )
    except ValueError:
        return None


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _status(value: Any) -> str:
    value = str(value or "").upper().strip()
    return value if value in {"ACTIVE", "ENDED", "UNKNOWN"} else "UNKNOWN"


def _file_status(value: Any, attempt: Any = None) -> str:
    value = str(value or "").upper().strip()
    if value in {"PENDING", "AVAILABLE", "UNAVAILABLE", "INVALID", "MANUAL_REVIEW"}:
        return value
    attempt = str(attempt or "").upper().strip()
    if attempt in (DownloadStatus.SUCCESS, DownloadStatus.DUPLICATE_SKIPPED):
        return "AVAILABLE"
    if attempt in (DownloadStatus.INVALID_FILE,):
        return "INVALID"
    if attempt in (DownloadStatus.UNKNOWN_DOCUMENT_TYPE, DownloadStatus.MANUAL_REVIEW_REQUIRED):
        return "MANUAL_REVIEW"
    if attempt == DownloadStatus.DRY_RUN:
        return "PENDING"
    return "UNAVAILABLE" if attempt else "PENDING"


def normalize_source_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """정규화된 ``source_metadata``를 반환한다.

    문서/product identity와 identity version은 DB 최상위 컬럼이므로 JSONB
    중복 필드로 저장하지 않는다. 입력 mapping을 복사하므로 호출자가 가진
    migration provenance 객체를 변경하지 않으며, ``None``/비객체 입력은
    빈 metadata로 처리한다.
    """

    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): child
        for key, child in value.items()
        if str(key) not in _SOURCE_METADATA_IDENTITY_KEYS
    }


def _validate_identity_keys(values: Mapping[str, Any]) -> None:
    """최종 v4 접두사 key 쌍만 DB 쓰기에 허용한다."""
    document_key = str(values.get("document_key") or "")
    product_key = str(values.get("product_version_key") or "")
    if _DOCUMENT_KEY_RE.fullmatch(document_key) is None:
        raise ValueError("document_key는 DOC_ 접두사 + Base62 10자리여야 합니다")
    if _PRODUCT_VERSION_KEY_RE.fullmatch(product_key) is None:
        raise ValueError("product_version_key는 PROD_VER_ 접두사 + Base62 10자리여야 합니다")
    if "identity_version" in values and int(values["identity_version"] or 0) != IDENTITY_VERSION:
        raise ValueError(f"identity_version은 {IDENTITY_VERSION}만 허용됩니다")


def payload_from_record(
    record: Any,
    *,
    version: ProductVersion | Any | None = None,
    document: Document | Any | None = None,
    run_id: str | None = None,
    collector_type: str = "PYTHON",
    now: datetime | None = None,
) -> dict[str, Any]:
    """ManifestRecord/ProductVersion/Document를 DB payload로 변환한다."""
    now = now or _now()
    if version is not None:
        # 문서 링크가 없는 NO_DOCUMENT_LINK 결과도 상품 버전과 기존
        # ManifestRecord 키를 기준으로 안정적인 행을 만들 수 있어야 한다.
        identity_document = document or Document(
            getattr(record, "document_type", "") or "UNKNOWN_DOCUMENT_TYPE",
            getattr(record, "document_label", "") or "",
            getattr(record, "document_url", "") or "",
            getattr(record, "original_filename", "") or "",
        )
        identity = identity_for(version, identity_document, record)
        metadata = metadata_for(version, identity_document, record)
    else:
        identity = None
        metadata = {}
    attempt = str(getattr(record, "download_status", "") or "").upper() or None
    d_type = getattr(record, "document_type", "") or getattr(document, "document_type", None)
    version_date = getattr(version, "target_date", None) if version is not None else None
    product_name = getattr(record, "product_name_raw", "") or getattr(version, "product_name_raw", "")
    normalized = getattr(record, "product_name_normalized", "") or product_name
    saved_relative_path = getattr(record, "saved_relative_path", "") or None
    sha256 = str(getattr(record, "sha256", "") or "").lower() or None
    file_status = _file_status("", attempt)
    has_file_evidence = bool(saved_relative_path or sha256)
    if (
        attempt == DownloadStatus.DUPLICATE_SKIPPED
        and not has_file_evidence
    ):
        # --retry-failed에서 DB 기록이 없는 신규 문서를
        # "건너뜀" 상태로 남겨도 물리 파일이 생긴 것은 아니다.
        # 경로/SHA 증거가 없는 DUPLICATE는 AVAILABLE로 승격시키지
        # 않아 다음 정상 수집에서 다시 처리하게 한다.
        file_status = "PENDING"
    elif attempt == DownloadStatus.SUCCESS and not has_file_evidence:
        # SUCCESS라면 저장 상대경로나 SHA 중 하나는 반드시 있어야 한다.
        # 불완전 payload를 AVAILABLE로 확정하면 이후 수집이 영구히
        # 생략될 수 있으므로 복구 가능한 물리 미확인 상태로 둔다.
        file_status = "UNAVAILABLE"
    completed_file = file_status == "AVAILABLE"
    result = {
        "document_key": identity.document_key if identity else getattr(record, "document_key", ""),
        "product_version_key": identity.product_version_key if identity else getattr(record, "product_version_key", ""),
        "company_code": getattr(record, "company_code", "") or getattr(version, "company_code", ""),
        "company_name": getattr(record, "company_name", "") or getattr(version, "company_name", ""),
        "product_category": getattr(record, "product_category", "") or getattr(version, "product_category", "") or None,
        "source_product_id": getattr(record, "source_product_id", "") or getattr(version, "source_product_id", "") or None,
        "product_name": product_name,
        "product_name_normalized": normalized,
        "sale_status": _status(
            (getattr(record, "normalized_sale_status", "") or getattr(record, "sale_status", ""))
            or (getattr(version, "normalized_sale_status", "") if version is not None else "")
        ),
        "sale_status_raw": (
            getattr(record, "source_sale_status", "") or getattr(record, "sale_status", "")
            or (getattr(version, "sale_status", "") if version is not None else "")
        ) or None,
        "sale_start_date": _as_date(getattr(record, "sale_start_date", "") or getattr(version, "sale_start_date", None)),
        "sale_end_date": _as_date(getattr(record, "sale_end_date", "") or getattr(version, "sale_end_date", None)),
        "status_checked_at": _as_datetime(getattr(record, "status_checked_at", "")),
        "status_changed_at": _as_datetime(getattr(record, "status_changed_at", "")),
        "status_missing_count": int(getattr(record, "status_missing_count", 0) or 0),
        "document_date": _as_date(getattr(record, "target_date", "") or version_date),
        "document_date_basis": getattr(record, "date_basis", "") or getattr(version, "date_basis", "") or None,
        "document_type": d_type or None,
        "document_label": getattr(record, "document_label", "") or getattr(document, "document_label", None),
        "source_page_url": getattr(record, "source_page_url", "") or getattr(version, "source_page_url", "") or None,
        "document_url": getattr(record, "document_url", "") or getattr(document, "document_url", None),
        "original_filename": getattr(record, "original_filename", "") or getattr(document, "original_filename", None),
        "source_metadata": metadata,
        "saved_relative_path": saved_relative_path,
        "file_size": int(getattr(record, "file_size", 0) or 0) or None,
        "sha256": sha256,
        "file_status": file_status,
        "last_attempt_status": attempt,
        "error_message": getattr(record, "error_message", "") or None,
        "downloaded_at": _as_datetime(getattr(record, "downloaded_at", "")) if completed_file else None,
        "last_attempt_at": now,
        "last_seen_run_id": run_id or getattr(record, "run_id", "") or None,
        "last_download_run_id": (
            run_id or getattr(record, "run_id", "") or None
            if completed_file
            else None
        ),
        "last_status_run_id": getattr(record, "status_run_id", "") or None,
        "last_seen_at": now,
        "collector_type": collector_type,
        "identity_version": int(getattr(identity, "identity_version", IDENTITY_VERSION)) if identity else IDENTITY_VERSION,
    }
    return result


class DisclosureDocumentRepository:
    """재사용 연결 + 문서별 짧은 UPSERT 저장소."""

    def __init__(
        self,
        config: DatabaseConfig,
        *,
        connection_factory: Callable[..., Any] = psycopg.connect,
        table_name: str = TABLE_NAME,
    ) -> None:
        self.config = config
        self.connection_factory = connection_factory
        if not table_name.replace("_", "").isalnum():
            raise ValueError("안전하지 않은 table_name")
        self.table_name = table_name
        self._connection: Any | None = None

    @classmethod
    def from_env(cls, env_file: str | Path | None = None, **kwargs: Any) -> "DisclosureDocumentRepository":
        return cls(DatabaseConfig.from_env(env_file), **kwargs)

    @property
    def connection(self) -> Any:
        if self._connection is None or getattr(self._connection, "closed", False):
            kwargs = self.config.connect_kwargs()
            from psycopg.rows import dict_row

            self._connection = self.connection_factory(**kwargs, row_factory=dict_row)
        return self._connection

    @contextmanager
    def _transaction(self):
        connection = self.connection
        transaction = getattr(connection, "transaction", None)
        with (transaction() if transaction else nullcontext()):
            yield connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "DisclosureDocumentRepository":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def get_by_document_key(self, key: str) -> dict[str, Any] | None:
        def operation(connection: Any):
            return connection.execute(
                f"SELECT * FROM {self.table_name} WHERE document_key = %s", (key,)
            ).fetchone()

        row = self._with_reconnect(operation)
        return self._row_to_dict(row)

    def load_company_rows(self, company_code: str) -> dict[str, dict[str, Any]]:
        def operation(connection: Any):
            return connection.execute(
                f"SELECT * FROM {self.table_name} WHERE company_code = %s", (company_code,)
            ).fetchall()

        rows = self._with_reconnect(operation)
        return {
            str((row.get("document_key") if isinstance(row, Mapping) else row[1])): self._row_to_dict(row)
            for row in rows
        }

    def upsert_seen(self, payload: Mapping[str, Any] | DocumentPayload) -> None:
        self._upsert(self._payload_dict(payload), seen_only=True)

    def upsert_result(self, payload: Mapping[str, Any] | DocumentPayload) -> None:
        self._upsert(self._payload_dict(payload), seen_only=False)

    def update_status_rows_detailed(
        self, rows: Iterable[Mapping[str, Any]]
    ) -> StatusUpdateResult:
        rows = list(rows)

        def operation(connection: Any) -> StatusUpdateResult:
            updated = stale_noop = missing = 0
            for row in rows:
                document_key = str(row.get("document_key", "")).strip()
                if not document_key:
                    raise ValueError("update_status_rows에는 document_key가 필요합니다")
                params = (
                    _status(row.get("sale_status")),
                    row.get("sale_status_raw"),
                    _as_date(row.get("sale_start_date")),
                    _as_date(row.get("sale_end_date")),
                    _as_datetime(row.get("status_checked_at")) or _now(),
                    _as_datetime(row.get("status_changed_at")),
                    int(row.get("status_missing_count", 0) or 0),
                    row.get("last_status_run_id"),
                    row.get("saved_relative_path"),
                    document_key,
                )
                cursor = connection.execute(
                    f"""
                    UPDATE {self.table_name}
                    SET sale_status=%s, sale_status_raw=%s, sale_start_date=%s,
                        sale_end_date=%s, status_checked_at=%s, status_changed_at=%s,
                        status_missing_count=%s, last_status_run_id=%s,
                        saved_relative_path=COALESCE(%s, saved_relative_path)
                    WHERE document_key=%s
                      AND (status_checked_at IS NULL OR status_checked_at <= %s)
                    """,
                    params + (params[4],),
                )
                rowcount = getattr(cursor, "rowcount", 0)
                if isinstance(rowcount, int) and rowcount > 0:
                    updated += rowcount
                    continue
                # 0건은 document_key 누락과 더 최신의 status_checked_at이
                # 이미 저장된 stale no-op 두 경우다. 후자는 요청한
                # 최종 상태보다 DB가 더 최신이므로 정상 처리된 행으로
                # 계산해 outbox가 영구히 미ACK로 남지 않게 한다.
                exists = connection.execute(
                    f"SELECT 1 FROM {self.table_name} WHERE document_key=%s",
                    (document_key,),
                ).fetchone()
                if exists is not None:
                    stale_noop += 1
                else:
                    missing += 1
            return StatusUpdateResult(
                requested=len(rows),
                updated=updated,
                stale_noop=stale_noop,
                missing=missing,
            )

        return self._with_reconnect_transaction(operation)

    @staticmethod
    def _payload_dict(payload: Mapping[str, Any] | DocumentPayload) -> dict[str, Any]:
        values = asdict(payload) if isinstance(payload, DocumentPayload) else dict(payload)
        values.setdefault("identity_version", IDENTITY_VERSION)
        _validate_identity_keys(values)
        values["source_metadata"] = normalize_source_metadata(values.get("source_metadata"))
        values["sale_status"] = _status(values.get("sale_status"))
        values["file_status"] = _file_status(values.get("file_status"), values.get("last_attempt_status"))
        values["status_checked_at"] = _as_datetime(values.get("status_checked_at"))
        values["status_changed_at"] = _as_datetime(values.get("status_changed_at"))
        values["last_attempt_at"] = _as_datetime(values.get("last_attempt_at")) or _now()
        values["last_seen_at"] = _as_datetime(values.get("last_seen_at")) or values["last_attempt_at"]
        for field in ("sale_start_date", "sale_end_date", "document_date"):
            values[field] = _as_date(values.get(field))
        return values

    def _upsert(self, values: dict[str, Any], *, seen_only: bool) -> None:
        if seen_only:
            # 발견 이벤트는 다운로드 시도가 아니므로 attempt 시각을 갱신하지 않는다.
            values["last_attempt_at"] = None
        columns = [
            "document_key", "product_version_key", "collector_type", "company_code", "company_name",
            "product_category", "source_product_id", "product_name", "product_name_normalized",
            "sale_status", "sale_status_raw", "sale_start_date", "sale_end_date", "status_checked_at",
            "status_changed_at", "status_missing_count", "document_date", "document_date_basis", "document_type",
            "document_label", "source_page_url", "document_url", "original_filename", "source_metadata",
            "saved_relative_path", "file_size", "sha256", "file_status", "last_attempt_status", "error_message",
            "downloaded_at", "last_attempt_at", "last_seen_run_id", "last_download_run_id", "last_status_run_id",
            "last_seen_at", "identity_version",
        ]
        values.setdefault("collector_type", "PYTHON")
        values.setdefault("status_missing_count", 0)
        values.setdefault("file_status", "PENDING")
        values.setdefault("source_metadata", {})
        params = [Jsonb(values.get(column)) if column == "source_metadata" else values.get(column) for column in columns]
        insert = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))
        newer_attempt = "(rs.last_attempt_at IS NULL OR EXCLUDED.last_attempt_at >= rs.last_attempt_at)"
        newer_seen = "(rs.last_seen_at IS NULL OR EXCLUDED.last_seen_at >= rs.last_seen_at)"
        newer_result = f"({newer_attempt} OR {newer_seen})"
        newer_status = (
            "(rs.status_checked_at IS NULL OR "
            "(EXCLUDED.status_checked_at IS NOT NULL AND "
            "EXCLUDED.status_checked_at >= rs.status_checked_at))"
        )
        # 발견/상품 메타데이터는 관측 이벤트 시각을, 결과/문서 필드는
        # 발견 또는 시도 이벤트 중 더 최신인 시각을 기준으로 갱신한다.
        newer_status_event = f"({newer_seen} AND {newer_status})"
        # Runtime metadata is additive, but immutable migration provenance must
        # survive a later discovery/download event.  Preserve those keys from
        # the existing row when present while allowing ordinary enrichment
        # fields (for example final_url) to update.
        merged_metadata = """
            (
                COALESCE(rs.source_metadata, '{}'::jsonb) || EXCLUDED.source_metadata
                || CASE WHEN rs.source_metadata ? 'migration'
                        THEN jsonb_build_object('migration', rs.source_metadata->'migration')
                        ELSE '{}'::jsonb END
                || CASE WHEN rs.source_metadata ? 'checkpoint_key'
                        THEN jsonb_build_object('checkpoint_key', rs.source_metadata->'checkpoint_key')
                        ELSE '{}'::jsonb END
                || CASE WHEN rs.source_metadata ? 'source_locator'
                        THEN jsonb_build_object('source_locator', rs.source_metadata->'source_locator')
                        ELSE '{}'::jsonb END
                || CASE WHEN rs.source_metadata ? 'migration_verification'
                        THEN jsonb_build_object(
                            'migration_verification',
                            rs.source_metadata->'migration_verification'
                        )
                        ELSE '{}'::jsonb END
            )
        """
        if seen_only:
            updates = """
                product_version_key=CASE WHEN {newer_seen} THEN EXCLUDED.product_version_key ELSE rs.product_version_key END,
                collector_type=CASE WHEN {newer_seen} THEN EXCLUDED.collector_type ELSE rs.collector_type END,
                company_name=CASE WHEN {newer_seen} THEN EXCLUDED.company_name ELSE rs.company_name END,
                product_category=CASE WHEN {newer_seen} THEN EXCLUDED.product_category ELSE rs.product_category END,
                source_product_id=CASE WHEN {newer_seen} THEN EXCLUDED.source_product_id ELSE rs.source_product_id END,
                product_name=CASE WHEN {newer_seen} THEN EXCLUDED.product_name ELSE rs.product_name END,
                product_name_normalized=CASE WHEN {newer_seen} THEN EXCLUDED.product_name_normalized ELSE rs.product_name_normalized END,
                sale_status=CASE WHEN {newer_status_event} THEN EXCLUDED.sale_status ELSE rs.sale_status END,
                sale_status_raw=CASE WHEN {newer_status_event} THEN EXCLUDED.sale_status_raw ELSE rs.sale_status_raw END,
                sale_start_date=CASE WHEN {newer_status_event} THEN EXCLUDED.sale_start_date ELSE rs.sale_start_date END,
                sale_end_date=CASE WHEN {newer_status_event} THEN EXCLUDED.sale_end_date ELSE rs.sale_end_date END,
                status_checked_at=CASE WHEN {newer_status_event} THEN EXCLUDED.status_checked_at ELSE rs.status_checked_at END,
                status_changed_at=CASE WHEN {newer_status_event} THEN EXCLUDED.status_changed_at ELSE rs.status_changed_at END,
                status_missing_count=CASE WHEN {newer_status_event} THEN EXCLUDED.status_missing_count ELSE rs.status_missing_count END,
                last_seen_run_id=CASE WHEN {newer_seen} THEN EXCLUDED.last_seen_run_id ELSE rs.last_seen_run_id END,
                last_seen_at=CASE WHEN {newer_seen} THEN EXCLUDED.last_seen_at ELSE rs.last_seen_at END,
                source_metadata=CASE WHEN {newer_seen} THEN {merged_metadata} ELSE rs.source_metadata END,
                identity_version=CASE WHEN {newer_seen} THEN EXCLUDED.identity_version ELSE rs.identity_version END
            """.format(
                newer_seen=newer_seen,
                newer_status_event=newer_status_event,
                merged_metadata=merged_metadata,
            )
        else:
            updates = """
                product_version_key=CASE WHEN {newer_seen} THEN EXCLUDED.product_version_key ELSE rs.product_version_key END,
                collector_type=CASE WHEN {newer_seen} THEN EXCLUDED.collector_type ELSE rs.collector_type END,
                company_name=CASE WHEN {newer_seen} THEN EXCLUDED.company_name ELSE rs.company_name END,
                product_category=CASE WHEN {newer_seen} THEN EXCLUDED.product_category ELSE rs.product_category END,
                source_product_id=CASE WHEN {newer_seen} THEN EXCLUDED.source_product_id ELSE rs.source_product_id END,
                product_name=CASE WHEN {newer_seen} THEN EXCLUDED.product_name ELSE rs.product_name END,
                product_name_normalized=CASE WHEN {newer_seen} THEN EXCLUDED.product_name_normalized ELSE rs.product_name_normalized END,
                sale_status=CASE WHEN {newer_status_event} THEN EXCLUDED.sale_status ELSE rs.sale_status END,
                sale_status_raw=CASE WHEN {newer_status_event} THEN EXCLUDED.sale_status_raw ELSE rs.sale_status_raw END,
                sale_start_date=CASE WHEN {newer_status_event} THEN EXCLUDED.sale_start_date ELSE rs.sale_start_date END,
                sale_end_date=CASE WHEN {newer_status_event} THEN EXCLUDED.sale_end_date ELSE rs.sale_end_date END,
                status_checked_at=CASE WHEN {newer_status_event} THEN EXCLUDED.status_checked_at ELSE rs.status_checked_at END,
                status_changed_at=CASE WHEN {newer_status_event} THEN EXCLUDED.status_changed_at ELSE rs.status_changed_at END,
                status_missing_count=CASE WHEN {newer_status_event} THEN EXCLUDED.status_missing_count ELSE rs.status_missing_count END,
                document_date=CASE WHEN {newer_result} THEN COALESCE(EXCLUDED.document_date, rs.document_date) ELSE rs.document_date END,
                document_date_basis=CASE WHEN {newer_result} THEN COALESCE(EXCLUDED.document_date_basis, rs.document_date_basis) ELSE rs.document_date_basis END,
                document_type=CASE WHEN {newer_result} THEN COALESCE(EXCLUDED.document_type, rs.document_type) ELSE rs.document_type END,
                document_label=CASE WHEN {newer_result} THEN COALESCE(EXCLUDED.document_label, rs.document_label) ELSE rs.document_label END,
                source_page_url=CASE WHEN {newer_result} THEN COALESCE(EXCLUDED.source_page_url, rs.source_page_url) ELSE rs.source_page_url END,
                document_url=CASE WHEN {newer_result} THEN COALESCE(EXCLUDED.document_url, rs.document_url) ELSE rs.document_url END,
                original_filename=CASE WHEN {newer_result} THEN COALESCE(EXCLUDED.original_filename, rs.original_filename) ELSE rs.original_filename END,
                source_metadata=CASE WHEN {newer_seen} THEN {merged_metadata} ELSE rs.source_metadata END,
                file_status=CASE WHEN {newer_attempt} THEN CASE WHEN EXCLUDED.last_attempt_status='DRY_RUN' AND rs.file_status='AVAILABLE' THEN rs.file_status ELSE EXCLUDED.file_status END ELSE rs.file_status END,
                saved_relative_path=CASE WHEN {newer_attempt} THEN CASE WHEN EXCLUDED.last_attempt_status='DRY_RUN' AND rs.file_status='AVAILABLE' THEN rs.saved_relative_path ELSE EXCLUDED.saved_relative_path END ELSE rs.saved_relative_path END,
                file_size=CASE WHEN {newer_attempt} THEN CASE WHEN EXCLUDED.last_attempt_status='DRY_RUN' AND rs.file_status='AVAILABLE' THEN rs.file_size ELSE EXCLUDED.file_size END ELSE rs.file_size END,
                sha256=CASE WHEN {newer_attempt} THEN CASE WHEN EXCLUDED.last_attempt_status='DRY_RUN' AND rs.file_status='AVAILABLE' THEN rs.sha256 ELSE EXCLUDED.sha256 END ELSE rs.sha256 END,
                last_attempt_status=CASE WHEN {newer_attempt} THEN EXCLUDED.last_attempt_status ELSE rs.last_attempt_status END,
                error_message=CASE WHEN {newer_attempt} THEN EXCLUDED.error_message ELSE rs.error_message END,
                last_attempt_at=CASE WHEN {newer_attempt} THEN EXCLUDED.last_attempt_at ELSE rs.last_attempt_at END,
                downloaded_at=CASE WHEN {newer_result} THEN CASE WHEN EXCLUDED.downloaded_at IS NOT NULL AND (rs.downloaded_at IS NULL OR EXCLUDED.downloaded_at >= rs.downloaded_at) THEN EXCLUDED.downloaded_at ELSE rs.downloaded_at END ELSE rs.downloaded_at END,
                last_download_run_id=CASE WHEN {newer_attempt} AND EXCLUDED.last_download_run_id IS NOT NULL THEN EXCLUDED.last_download_run_id ELSE rs.last_download_run_id END,
                last_status_run_id=CASE WHEN {newer_status_event} AND EXCLUDED.last_status_run_id IS NOT NULL THEN EXCLUDED.last_status_run_id ELSE rs.last_status_run_id END,
                last_seen_run_id=CASE WHEN {newer_seen} THEN EXCLUDED.last_seen_run_id ELSE rs.last_seen_run_id END,
                last_seen_at=CASE WHEN {newer_seen} THEN EXCLUDED.last_seen_at ELSE rs.last_seen_at END,
                identity_version=CASE WHEN {newer_result} THEN EXCLUDED.identity_version ELSE rs.identity_version END
            """.format(
                newer_attempt=newer_attempt,
                newer_seen=newer_seen,
                newer_result=newer_result,
                newer_status_event=newer_status_event,
                merged_metadata=merged_metadata,
            )
        # key 충돌을 조용히 덮어쓰지 않도록 안정적인 identity 문맥이
        # 일치할 때만 기존 행을 갱신한다.  짧은 key는 이론적으로 충돌할
        # 수 있으므로, WHERE가 거짓이면 명시적으로 fail-closed 한다.
        identity_guard = """
            rs.product_version_key IS NOT DISTINCT FROM EXCLUDED.product_version_key
            AND rs.company_code IS NOT DISTINCT FROM EXCLUDED.company_code
            AND rs.source_product_id IS NOT DISTINCT FROM EXCLUDED.source_product_id
            AND rs.document_type IS NOT DISTINCT FROM EXCLUDED.document_type
            AND rs.document_date IS NOT DISTINCT FROM EXCLUDED.document_date
            AND COALESCE(
                NULLIF(rs.source_metadata->>'checkpoint_key', ''),
                NULLIF(rs.source_metadata->>'source_locator', ''),
                NULLIF(rs.document_url, ''),
                NULLIF(rs.original_filename, ''),
                ''
            ) IS NOT DISTINCT FROM COALESCE(
                NULLIF(EXCLUDED.source_metadata->>'checkpoint_key', ''),
                NULLIF(EXCLUDED.source_metadata->>'source_locator', ''),
                NULLIF(EXCLUDED.document_url, ''),
                NULLIF(EXCLUDED.original_filename, ''),
                ''
            )
        """
        sql = (
            f"INSERT INTO {self.table_name} AS rs ({insert}) VALUES ({placeholders}) "
            f"ON CONFLICT (document_key) DO UPDATE SET {updates} "
            f"WHERE {identity_guard} RETURNING rs.document_key"
        )

        def operation(connection: Any) -> None:
            cursor = connection.execute(sql, params)
            rowcount = getattr(cursor, "rowcount", None)
            if isinstance(rowcount, int) and rowcount == 0:
                # PostgreSQL's ON CONFLICT ... WHERE reports zero rows when an
                # existing key failed the semantic guard.  Do not silently
                # drop the event or create a second row with a random key.
                raise IdentityKeyCollisionError(
                    "document_key 충돌: 동일 key의 상품/문서 identity 문맥이 다릅니다 "
                    f"(document_key={values.get('document_key')!r})"
                )

        self._with_reconnect_transaction(operation)

    def _discard_connection(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
            try:
                connection.close()
            except Exception:
                pass

    def _with_reconnect(self, operation: Callable[[Any], Any]) -> Any:
        """연결 단절만 1회 재연결한다. SQL/제약 오류는 그대로 전파한다."""
        for attempt in range(2):
            try:
                return operation(self.connection)
            except (psycopg.OperationalError, psycopg.InterfaceError):
                self._discard_connection()
                if attempt:
                    raise
        raise AssertionError("unreachable")

    def _with_reconnect_transaction(self, operation: Callable[[Any], Any]) -> Any:
        def transactional(connection: Any) -> Any:
            with self._transaction() as tx_connection:
                return operation(tx_connection)

        return self._with_reconnect(transactional)

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        if isinstance(row, Mapping):
            return dict(row)
        if hasattr(row, "keys"):
            return dict(row)
        columns = (
            "document_id", "document_key", "product_version_key", "collector_type", "company_code",
            "company_name", "product_category", "source_product_id", "product_name", "product_name_normalized",
            "sale_status", "sale_status_raw", "sale_start_date", "sale_end_date", "status_checked_at",
            "status_changed_at", "status_missing_count", "document_date", "document_date_basis", "document_type",
            "document_label", "source_page_url", "document_url", "original_filename", "source_metadata",
            "saved_relative_path", "file_size", "sha256", "file_status", "last_attempt_status",
            "error_message", "downloaded_at", "last_seen_run_id", "last_download_run_id", "last_status_run_id",
            "last_seen_at", "created_at", "updated_at", "last_attempt_at", "identity_version",
        )
        return dict(zip(columns, row))


RepositoryFactory = Callable[[], Any]


def open_document_repository(
    factory: RepositoryFactory | None = None,
    *,
    env_file: str | Path | None = None,
) -> Any:
    """현재 DB repository 계약으로 새 연결 객체를 생성한다."""

    repository = (
        factory()
        if factory is not None
        else DisclosureDocumentRepository.from_env(env_file=env_file)
    )
    if repository is None:
        raise RuntimeError("repository_factory가 DB repository를 반환하지 않았습니다")
    if not callable(getattr(repository, "close", None)):
        raise RuntimeError("DB repository는 close() 종료 계약을 구현해야 합니다")
    return repository


def close_document_repository(repository: Any) -> None:
    """``open_document_repository``로 생성한 repository를 종료한다."""

    if repository is not None:
        repository.close()
