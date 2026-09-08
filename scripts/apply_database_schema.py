"""`.env`의 PostgreSQL에 프로젝트 DB 스키마를 적용한다.

사용 예::

    uv run python scripts/apply_database_schema.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.crawler_logger import setup_logging  # noqa: E402
from crawler.db_readiness import (  # noqa: E402
    MIGRATION_ADVISORY_LOCK_KEY,
    is_exact_manifest_source_row_check,
    is_exact_identity_v4_check,
    parse_postgres_integer_default,
)
from crawler.document_repository import DatabaseConfig  # noqa: E402

DEFAULT_SCHEMA_PATH = (
    PROJECT_ROOT / "database" / "schema" / "001_create_rs_disclosure_documents.sql"
)
DEFAULT_MIGRATIONS_DIR = PROJECT_ROOT / "database" / "schema"
EXPECTED_COLUMNS = {
    "document_id",
    "document_key",
    "product_version_key",
    "collector_type",
    "company_code",
    "company_name",
    "product_category",
    "source_product_id",
    "product_name",
    "product_name_normalized",
    "sale_status",
    "sale_status_raw",
    "sale_start_date",
    "sale_end_date",
    "status_checked_at",
    "status_changed_at",
    "status_missing_count",
    "document_date",
    "document_date_basis",
    "document_type",
    "document_label",
    "source_page_url",
    "document_url",
    "original_filename",
    "source_metadata",
    "saved_relative_path",
    "file_size",
    "sha256",
    "file_status",
    "last_attempt_status",
    "error_message",
    "downloaded_at",
    "last_seen_run_id",
    "last_download_run_id",
    "last_status_run_id",
    "last_seen_at",
    "created_at",
    "updated_at",
    "last_attempt_at",
    "identity_version",
}
EXPECTED_CONSTRAINTS = {
    "rs_disclosure_documents_pkey",
    "uq_rs_disclosure_documents_document_key",
    "ck_rs_disclosure_documents_document_key",
    "ck_rs_disclosure_documents_product_version_key",
    "ck_rs_disclosure_documents_identity_version",
    "ck_rs_disclosure_documents_collector_type",
    "ck_rs_disclosure_documents_sale_status",
    "ck_rs_disclosure_documents_document_type",
    "ck_rs_disclosure_documents_file_status",
    "ck_rs_disclosure_documents_last_attempt_status",
    "ck_rs_disclosure_documents_status_missing_count",
    "ck_rs_disclosure_documents_file_size",
    "ck_rs_disclosure_documents_sha256",
    "ck_rs_disclosure_documents_manifest_source_row",
}
EXPECTED_INDEXES = {
    "ix_rs_disclosure_documents_company_date",
    "ix_rs_disclosure_documents_product_version",
    "ix_rs_disclosure_documents_sale_status",
    "ix_rs_disclosure_documents_file_status",
    "ix_rs_disclosure_documents_last_seen",
    "ix_rs_disclosure_documents_sha256",
    "ix_rs_disclosure_documents_last_attempt",
    "uq_rs_disclosure_documents_manifest_source_row",
}

EXPECTED_COLUMN_TYPES = {
    "last_attempt_at": "timestamp with time zone",
    "identity_version": "smallint",
}
EXPECTED_KEY_LENGTHS = {
    "document_key": 14,
    "product_version_key": 19,
}
EXPECTED_KEY_CONSTRAINTS = {
    "ck_rs_disclosure_documents_document_key": "document_key",
    "ck_rs_disclosure_documents_product_version_key": "product_version_key",
}
EXPECTED_KEY_PATTERNS = {
    "document_key": "^DOC_[0-9A-Za-z]{10}$",
    "product_version_key": "^PROD_VER_[0-9A-Za-z]{10}$",
}
EXPECTED_IDENTITY_VERSION = 4


def _parse_integer_default(value: object) -> int | None:
    """PostgreSQL이 표시한 단순 정수 DEFAULT를 정확히 해석한다."""
    return parse_postgres_integer_default(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PostgreSQL 상품공시 문서 테이블 생성")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PROJECT_ROOT / ".env",
        help="DB 접속정보 .env 경로",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA_PATH,
        help="적용할 SQL 스키마 경로",
    )
    return parser


def load_db_config(env_file: Path) -> dict[str, object]:
    if not env_file.is_file():
        raise FileNotFoundError(f".env 파일을 찾을 수 없습니다: {env_file}")
    # DatabaseConfig가 애플리케이션과 동일한 .env 파싱/환경변수 override,
    # SSL 및 timeout 계약을 단일하게 유지한다. 파일 존재 여부는 스키마
    # 도구의 기존 사전 검증으로 명확한 오류를 보장한다.
    return DatabaseConfig.from_env(env_file).connect_kwargs()


def table_exists(connection: psycopg.Connection) -> bool:
    row = connection.execute(
        "SELECT to_regclass('public.rs_disclosure_documents') IS NOT NULL"
    ).fetchone()
    return bool(row and row[0])


def verify_schema(connection: psycopg.Connection) -> int:
    rows = connection.execute(
        """
        SELECT column_name, data_type, column_default, is_nullable,
               character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'rs_disclosure_documents'
        ORDER BY ordinal_position
        """
    ).fetchall()
    columns = {str(row[0]) for row in rows}
    missing = sorted(EXPECTED_COLUMNS - columns)
    if missing:
        raise RuntimeError(f"테이블 필수 컬럼이 누락됐습니다: {', '.join(missing)}")
    by_name = {str(row[0]): row for row in rows}
    type_errors = []
    for name, expected_type in EXPECTED_COLUMN_TYPES.items():
        actual_type = str(by_name[name][1])
        if actual_type != expected_type:
            type_errors.append(f"{name}={actual_type} (expected {expected_type})")
    if type_errors:
        raise RuntimeError("테이블 컬럼 타입이 잘못됐습니다: " + ", ".join(type_errors))
    key_length_errors = []
    for name, expected_length in EXPECTED_KEY_LENGTHS.items():
        actual_length = by_name[name][4]
        if actual_length != expected_length:
            key_length_errors.append(f"{name}={actual_length} (expected {expected_length})")
    if key_length_errors:
        raise RuntimeError("짧은 identity key 길이가 잘못됐습니다: " + ", ".join(key_length_errors))
    if by_name["identity_version"][3] != "NO":
        raise RuntimeError("identity_version은 NOT NULL이어야 합니다")
    if _parse_integer_default(by_name["identity_version"][2]) != EXPECTED_IDENTITY_VERSION:
        raise RuntimeError("identity_version 기본값이 4이어야 합니다")

    constraint_rows = connection.execute(
        """
        SELECT constraint_name
        FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'rs_disclosure_documents'
        """
    ).fetchall()
    constraints = {str(row[0]) for row in constraint_rows}
    missing_constraints = sorted(EXPECTED_CONSTRAINTS - constraints)
    if missing_constraints:
        raise RuntimeError(
            "테이블 제약조건이 누락됐습니다: " + ", ".join(missing_constraints)
        )

    constraint_definitions = connection.execute(
        """
        SELECT conname, pg_get_constraintdef(oid), convalidated
        FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace
          AND conrelid = 'public.rs_disclosure_documents'::regclass
          AND conname = ANY(%s)
        """,
        (
            list(EXPECTED_KEY_CONSTRAINTS)
            + [
                "ck_rs_disclosure_documents_identity_version",
                "ck_rs_disclosure_documents_manifest_source_row",
            ],
        ),
    ).fetchall()
    for name, expected_column in EXPECTED_KEY_CONSTRAINTS.items():
        definition = next((str(row[1]) for row in constraint_definitions if str(row[0]) == name), "")
        # pg_get_constraintdef may render the column as either
        # ``document_key ~ ...`` or ``(document_key)::text ~ ...`` depending
        # on PostgreSQL version. Validate the semantic column/pattern pair,
        # not that formatting detail.
        expected_pattern = EXPECTED_KEY_PATTERNS[expected_column]
        if expected_column not in definition or expected_pattern not in definition:
            raise RuntimeError(f"{name}의 접두사 key CHECK가 잘못됐습니다: {definition}")

    identity_definition = next(
        (
            str(row[1])
            for row in constraint_definitions
            if str(row[0]) == "ck_rs_disclosure_documents_identity_version"
        ),
        "",
    )
    if not is_exact_identity_v4_check(identity_definition):
        raise RuntimeError(
            "ck_rs_disclosure_documents_identity_version의 v4 CHECK가 잘못됐습니다: "
            + identity_definition
        )

    provenance_definition = next(
        (
            str(row[1])
            for row in constraint_definitions
            if str(row[0]) == "ck_rs_disclosure_documents_manifest_source_row"
        ),
        "",
    )
    provenance_row = next(
        (row for row in constraint_definitions if str(row[0]) == "ck_rs_disclosure_documents_manifest_source_row"),
        None,
    )
    if provenance_row is None or not bool(provenance_row[2]) or not is_exact_manifest_source_row_check(provenance_definition):
        raise RuntimeError(
            "manifest source_row CHECK가 없거나 canonical 식이 아니거나 NOT VALID입니다: "
            f"definition={provenance_definition}, convalidated={None if provenance_row is None else provenance_row[2]}"
        )

    index_rows = connection.execute(
        """
        SELECT c.relname AS indexname, i.indisunique, i.indisvalid, i.indisready
        FROM pg_index AS i
        JOIN pg_class AS c ON c.oid = i.indexrelid
        JOIN pg_class AS t ON t.oid = i.indrelid
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND t.relname = 'rs_disclosure_documents'
        """
    ).fetchall()
    indexes = {str(row[0]) for row in index_rows}
    missing_indexes = sorted(EXPECTED_INDEXES - indexes)
    if missing_indexes:
        raise RuntimeError(f"테이블 인덱스가 누락됐습니다: {', '.join(missing_indexes)}")
    index_by_name = {str(row[0]): row for row in index_rows}
    provenance_index = index_by_name.get("uq_rs_disclosure_documents_manifest_source_row")
    if provenance_index is None or not all(bool(value) for value in provenance_index[1:4]):
        raise RuntimeError(
            "manifest source_row unique index가 없거나 유효하지 않습니다: "
            + repr(provenance_index)
        )

    forbidden_metadata = connection.execute(
        """
        SELECT COUNT(*)
        FROM public.rs_disclosure_documents
        WHERE source_metadata ?| ARRAY[
            'document_key', 'product_version_key', 'identity_version'
        ]
        """
    ).fetchone()
    if not forbidden_metadata or int(forbidden_metadata[0]) != 0:
        raise RuntimeError(
            "source_metadata에 authoritative identity 중복 필드가 남아 있습니다: "
            f"{None if not forbidden_metadata else forbidden_metadata[0]}"
        )

    trigger_row = connection.execute(
        """
        SELECT 1
        FROM information_schema.triggers
        WHERE event_object_schema = 'public'
          AND event_object_table = 'rs_disclosure_documents'
          AND trigger_name = 'trg_rs_disclosure_documents_updated_at'
        """
    ).fetchone()
    if trigger_row is None:
        raise RuntimeError("updated_at 자동 갱신 트리거가 누락됐습니다")

    return len(columns)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = setup_logging(None)

    try:
        schema_path = args.schema.resolve()
        if not schema_path.is_file():
            raise FileNotFoundError(f"SQL 스키마를 찾을 수 없습니다: {schema_path}")

        config = load_db_config(args.env_file.resolve())
        with psycopg.connect(**config) as connection:
            # 실행 중 수집기가 보유한 shared lock이 끝날 때까지 기다리고,
            # schema 적용 중에는 신규 수집 readiness가 통과하지 못하게 한다.
            connection.execute(
                "SELECT pg_advisory_lock(%s)",
                (MIGRATION_ADVISORY_LOCK_KEY,),
            )
            if table_exists(connection):
                logger.info("기존 rs_disclosure_documents 테이블을 확인합니다")
            else:
                sql_text = schema_path.read_text(encoding="utf-8")
                connection.execute(sql_text, prepare=False)
                logger.info("기본 스키마를 적용했습니다")

            # 001은 생성 스키마이고 이후 파일은 번호 순서의 증분 migration이다.
            # 이미 적용된 컬럼은 IF NOT EXISTS로 건너뛸 수 있으므로 재실행 가능하다.
            migration_paths = sorted(
                p for p in DEFAULT_MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")
                if p.name != schema_path.name and p.name > schema_path.name
            )
            for migration_path in migration_paths:
                connection.execute(migration_path.read_text(encoding="utf-8"), prepare=False)
                logger.info("증분 스키마 적용: %s", migration_path.name)

            column_count = verify_schema(connection)
            logger.info(
                "rs_disclosure_documents 스키마가 유효합니다(%d개 컬럼)",
                column_count,
            )
            return 0
    except (FileNotFoundError, OSError, ValueError, psycopg.Error, RuntimeError) as exc:
        logger.error("DB 스키마 적용에 실패했습니다: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
