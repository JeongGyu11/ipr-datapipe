"""문서 수집 결과 DTO와 DB 체크포인트 호환 계층.

전역 manifest 파일은 더 이상 런타임 정본이 아니다. ``ManifestRecord``와
호출 인터페이스는 어댑터 호환을 위해 남기되, 상태는 주입된 repository에
기록하며, 실행 감사 이벤트 JSONL은 별도 audit 경로에 append한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from models.document import DownloadStatus
from crawler.db_outbox import is_transient_database_error
from crawler.document_identity import (
    document_key_for_manifest,
    product_version_key_for_manifest,
)
from utils.crawler_logger import get_logger
from utils.network_io import durable_append_bytes, retry_file_operation

MANIFEST_COLUMNS = [
    "layout_version",
    "run_id",
    "company_code",
    "company_name",
    "product_category",
    "product_name_raw",
    "product_name_normalized",
    "source_product_id",
    "sale_status",
    "normalized_sale_status",
    "source_sale_status",
    "status_source",
    "status_check_result",
    "status_checked_at",
    "status_changed_at",
    "status_missing_count",
    "status_run_id",
    "sale_start_date",
    "sale_end_date",
    "disclosure_date",
    "revision_date",
    "target_date",
    "date_basis",
    "document_type",
    "document_label",
    "source_page_url",
    "document_url",
    "original_filename",
    "checkpoint_key",
    "saved_filename",
    "saved_relative_path",
    "file_extension",
    "content_type",
    "file_size",
    "sha256",
    "download_status",
    "downloaded_at",
    "error_message",
]


@dataclass
class ManifestRecord:
    layout_version: int | str = 2
    run_id: str = ""
    company_code: str = ""
    company_name: str = ""
    product_category: str = ""
    product_name_raw: str = ""
    product_name_normalized: str = ""
    source_product_id: str = ""
    sale_status: str = ""
    normalized_sale_status: str = ""
    source_sale_status: str = ""
    status_source: str = ""
    status_check_result: str = ""
    status_checked_at: str = ""
    status_changed_at: str = ""
    status_missing_count: int | str = ""
    status_run_id: str = ""
    sale_start_date: str = ""
    sale_end_date: str = ""
    disclosure_date: str = ""
    revision_date: str = ""
    target_date: str = ""
    date_basis: str = ""
    document_type: str = ""
    document_label: str = ""
    source_page_url: str = ""
    document_url: str = ""
    original_filename: str = ""
    # fetch/redirect와 독립적인 v4 문서 locator (DB source_metadata에서 복원)
    source_locator: str = ""
    # URL 없는 POST 문서는 download_hint별 plan key로 구분한다.
    checkpoint_key: str = ""
    saved_filename: str = ""
    saved_relative_path: str = ""
    file_extension: str = ""
    content_type: str = ""
    file_size: int | str = ""
    sha256: str = ""
    download_status: str = ""
    downloaded_at: str = ""
    error_message: str = ""
    # URL 대신 POST 파라미터 같은 download_hint 로 받는 문서도 있다.
    # 실행 중 summary 집계에만 사용하며 DB 문서 행에는
    # 저장하지 않는 runtime 힌트이다.
    has_download_target: bool = field(default=False, repr=False, compare=False)
    def key(self) -> str:
        """체크포인트 키. 같은 문서를 다시 받지 않기 위한 식별자."""
        if self.checkpoint_key:
            return f"PLAN|{self.checkpoint_key}"
        return "|".join(
            [
                self.company_code,
                self.source_product_id,
                self.product_name_raw,
                self.target_date,
                self.document_type,
                self.document_url or self.original_filename,
            ]
        )

    def to_row(self) -> dict:
        return {c: getattr(self, c, "") for c in MANIFEST_COLUMNS}


def fmt_date(value: date | None) -> str:
    return value.isoformat() if isinstance(value, date) else ""


@dataclass
class ManifestService:
    output_root: Path
    run_id: str
    audit_event_path: Path | None = None
    outbox: object | None = None
    records: list[ManifestRecord] = field(default_factory=list)
    previous: dict[str, dict] = field(default_factory=dict)
    repository: object | None = None

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    def load_previous(self, company_code: str | None = None) -> dict[str, dict]:
        """DB 체크포인트를 메모리 조회 맵으로 준비한다.

        repository가 없으면 빈 체크포인트에서 시작한다.
        """
        log = get_logger()
        result: dict[str, dict] = {}
        if self.repository is not None:
            if not company_code:
                raise ValueError("DB 체크포인트를 읽으려면 company_code가 필요합니다")
            rows = self.repository.load_company_rows(company_code)
            if rows:
                # repository는 document_key를 키로 하는 DB 행 맵을
                # 반환한다. 어댑터가 사용하는 체크포인트 DTO로 투영한다.
                iterable = rows.values() if isinstance(rows, dict) else rows
                self._merge_rows(
                    result,
                    [self._db_row_to_checkpoint(row) for row in iterable],
                )
        self.previous = result
        log.info("DB로부터 %d건의 체크포인트를 준비했습니다.", len(result))
        return result

    def _db_row_to_checkpoint(self, row: dict) -> dict:
        """DB 행을 어댑터 체크포인트 필드로 읽기 전용 변환한다."""
        def text(value):
            return value.isoformat() if hasattr(value, "isoformat") else (value or "")

        metadata = row.get("source_metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        attempt = row.get("last_attempt_status") or ""
        file_status = str(row.get("file_status") or "").upper()
        if file_status == "AVAILABLE":
            # DRY_RUN 같은 최신 비다운로드 시도가 있어도 DB의 물리 상태는
            # AVAILABLE로 보존된다. 실제 파일/SHA는 DownloadService가 다시
            # 검증하므로 유효한 파일을 불필요하게 재다운로드하지 않는다.
            checkpoint_status = (
                attempt if attempt in DownloadStatus.COMPLETED else DownloadStatus.SUCCESS
            )
        elif file_status == "INVALID":
            checkpoint_status = DownloadStatus.INVALID_FILE
        elif file_status == "PENDING" and not attempt:
            # 발견 행 INSERT 뒤 프로세스가 종료된 경우 terminal 결과가 없다.
            # 회사 잠금이 해제된 다음 실행에서는 진행 중인 요청이 아니므로
            # --retry-failed에서도 다시 처리할 수 있는 상태로 투영한다.
            checkpoint_status = DownloadStatus.DOWNLOAD_FAILED
        elif attempt in DownloadStatus.COMPLETED:
            # AVAILABLE이 아닌 모든 물리 상태(미설정 포함)는
            # 과거 SUCCESS/DUPLICATE 시도만으로 다운로드를 생략할 수 없다.
            checkpoint_status = DownloadStatus.DOWNLOAD_FAILED
        else:
            checkpoint_status = attempt
        saved_relative_path = row.get("saved_relative_path") or ""
        projected = {
            "layout_version": 2,
            "run_id": row.get("last_download_run_id") or row.get("last_seen_run_id") or "",
            "company_code": row.get("company_code") or "",
            "company_name": row.get("company_name") or "",
            "product_category": row.get("product_category") or "",
            "product_name_raw": row.get("product_name") or "",
            "product_name_normalized": row.get("product_name_normalized") or "",
            "source_product_id": row.get("source_product_id") or "",
            "sale_status": row.get("sale_status_raw") or row.get("sale_status") or "",
            "normalized_sale_status": row.get("sale_status") or "",
            "source_sale_status": row.get("sale_status_raw") or "",
            "status_source": "database",
            "status_check_result": "",
            "status_checked_at": text(row.get("status_checked_at")),
            "status_changed_at": text(row.get("status_changed_at")),
            "status_missing_count": row.get("status_missing_count") or 0,
            "status_run_id": row.get("last_status_run_id") or "",
            "sale_start_date": text(row.get("sale_start_date")),
            "sale_end_date": text(row.get("sale_end_date")),
            "disclosure_date": metadata.get("disclosure_date", ""),
            "revision_date": metadata.get("revision_date", ""),
            "target_date": text(row.get("document_date")),
            "date_basis": row.get("document_date_basis") or "",
            "document_type": row.get("document_type") or "",
            "document_label": row.get("document_label") or "",
            "source_page_url": row.get("source_page_url") or "",
            "document_url": row.get("document_url") or "",
            "original_filename": row.get("original_filename") or "",
            "source_locator": metadata.get("source_locator", ""),
            "checkpoint_key": metadata.get("checkpoint_key", ""),
            "saved_filename": Path(str(row.get("saved_relative_path") or "")).name,
            "saved_relative_path": saved_relative_path,
            "file_extension": Path(str(saved_relative_path)).suffix,
            "content_type": "",
            "file_size": row.get("file_size") or "",
            "sha256": row.get("sha256") or "",
            "download_status": checkpoint_status,
            "downloaded_at": text(row.get("downloaded_at")),
            "error_message": row.get("error_message") or "",
        }
        return projected

    @staticmethod
    def _merge_rows(target: dict[str, dict], rows) -> None:
        if not isinstance(rows, list):
            raise TypeError("DB checkpoint 행 목록은 배열이어야 합니다")
        for row in rows:
            if not isinstance(row, dict):
                continue
            values = {k: row.get(k, "") for k in MANIFEST_COLUMNS}
            # v4 locator는 DB source_metadata에서 복원되며 checkpoint DTO에는
            # 컬럼이 없어도 DTO 기본값으로 호환한다.
            values["source_locator"] = row.get("source_locator", "")
            # DB 행을 checkpoint DTO로 투영할 때도 현재 레이아웃 버전을 부여한다.
            if not values.get("layout_version"):
                values["layout_version"] = 2
            record = ManifestRecord(**values)
            previous = target.get(record.key())
            if previous is None or str(row.get("downloaded_at", "")) >= str(previous.get("downloaded_at", "")):
                normalized = {c: row.get(c, "") for c in MANIFEST_COLUMNS}
                normalized["source_locator"] = row.get("source_locator", "")
                normalized["layout_version"] = values["layout_version"]
                target[record.key()] = normalized

    @staticmethod
    def _require_runtime_v4_row(found, *, source: str) -> dict:
        """현재 repository 조회 결과에서 runtime identity v4만 허용한다."""

        if isinstance(found, dict):
            row = found
        else:
            try:
                row = dict(found)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"v4 runtime에서 {source} 조회 행 형식이 잘못됐습니다") from exc
        version = row.get("identity_version")
        if version not in (4, "4"):
            raise RuntimeError(
                f"v4 runtime에서 {source} legacy identity_version={version!r} 행을 사용할 수 없습니다"
            )
        return row

    def previous_row(self, record: ManifestRecord) -> dict | None:
        row = self.previous.get(record.key())
        if row is not None:
            return row
        if self.repository is None:
            return None
        key = document_key_for_manifest(record)
        found = self.repository.get_by_document_key(key)
        if not found:
            return None
        return self._db_row_to_checkpoint(
            self._require_runtime_v4_row(found, source="document_key")
        )

    def previous_rows_for_company(self, company_code: str) -> list[dict]:
        """현재 checkpoint에서 특정 보험사의 모든 문서 행을 반환한다."""

        wanted = str(company_code or "").strip().upper()
        return [
            dict(row)
            for row in self.previous.values()
            if str(row.get("company_code") or "").strip().upper() == wanted
        ]

    def replace_previous_rows(self, rows) -> None:
        """상태 재검증 결과를 문서 key별 DB 행에 즉시 반영한다.

        상태 폴더 이동이 ``MOVED``가 된 뒤 호출하며, DB 반영이 모두 성공한
        경우에만 호출부가 이동 저널을 ``COMMITTED``로 확정한다.
        """

        db_rows: list[dict] = []
        for source in rows:
            if not isinstance(source, dict):
                raise TypeError("교체할 DB checkpoint 행은 객체여야 합니다")
            values = {column: source.get(column, "") for column in MANIFEST_COLUMNS}
            values["source_locator"] = source.get("source_locator", "")
            values["layout_version"] = values.get("layout_version") or 2
            values["status_run_id"] = self.run_id
            record = ManifestRecord(**values)
            previous_row = record.to_row()
            self.previous[record.key()] = previous_row
            db_row = dict(values)
            if self.repository is not None:
                db_row["document_key"] = document_key_for_manifest(values)
                db_row["product_version_key"] = product_version_key_for_manifest(values)
                db_row.update(
                    sale_status=values.get("normalized_sale_status") or values.get("sale_status") or "UNKNOWN",
                    sale_status_raw=values.get("source_sale_status") or values.get("sale_status") or None,
                    saved_relative_path=values.get("saved_relative_path") or None,
                    last_status_run_id=values.get("status_run_id") or self.run_id,
                )
            db_rows.append(db_row)
        if self.repository is not None and db_rows:
            try:
                result = self.repository.update_status_rows_detailed(db_rows)
            except Exception as exc:
                # 재생으로 회복 가능한 연결 장애만 outbox에 기록한다.
                # SQL/제약/payload 버그를 넣으면 매 실행을 막는 poison이 된다.
                if self.outbox is not None and is_transient_database_error(exc):
                    self.outbox.append({"operation": "update_status_rows", "payload": db_rows})
                raise
            handled = int(result.handled)
            stale_noop = int(result.stale_noop)
            missing = int(result.missing)
            if stale_noop:
                get_logger().info("DB 판매상태 최신값 유지(stale no-op): %d건", stale_noop)
            if handled < len(db_rows) or missing:
                raise RuntimeError(
                    f"DB 판매상태 갱신 누락: "
                    f"요청 {len(db_rows)}건, 반영/최신유지 {handled}건, 누락 {missing}건"
                )

    # ------------------------------------------------------------------
    def add(self, record: ManifestRecord) -> ManifestRecord:
        record.run_id = self.run_id
        if not record.downloaded_at:
            record.downloaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.records.append(record)
        try:
            self._append_audit_event(record)
        except Exception as exc:
            # 감사 JSONL은 DB 정본이 아니므로 로컬/파일서버
            # 쓰기 실패가 문서 terminal DB UPSERT를 막아서는 안 된다.
            # DownloadService._add의 후속 DB 호출이 계속되도록
            # warning으로 격리한다.
            get_logger().warning("문서 감사 이벤트 기록 실패: %s", exc)
        return record

    def _append_audit_event(self, record: ManifestRecord) -> None:
        """문서 처리 감사 이벤트를 JSONL에 남긴다.

        이 이벤트는 DB 정본/체크포인트가 아니며, DB 장애 복구는 outbox가
        담당한다. 따라서 이벤트를 읽어 DB 상태를 복원하지 않는다.
        """
        if self.audit_event_path is None:
            return
        retry_file_operation(
            lambda: self.audit_event_path.parent.mkdir(parents=True, exist_ok=True),
            path=self.audit_event_path.parent,
            operation_name="실행 감사 이벤트 디렉터리 생성",
        )
        durable_append_bytes(
            self.audit_event_path,
            (json.dumps(record.to_row(), ensure_ascii=False) + "\n").encode("utf-8"),
        )

    # ------------------------------------------------------------------
    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.records:
            counts[record.download_status] = counts.get(record.download_status, 0) + 1
        return counts
