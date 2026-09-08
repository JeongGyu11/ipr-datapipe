"""선택적으로 실행하는 실제 PostgreSQL 계약 통합 테스트.

이 모듈은 ``RS_TEST_DB_*`` 환경변수가 *모두* 설정된 경우에만 실행한다.
운영 접속정보인 ``RS_DB_*`` 또는 프로젝트 ``.env``는 절대로 읽지 않는다.
따라서 일반 단위 테스트에서는 PostgreSQL 접속 시도 없이 모듈 전체가
skip된다.  설정된 데이터베이스 이름에 ``test``가 없으면 안전을 위해
수집용 DB일 가능성이 있으므로 즉시 실패한다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.types.json import Jsonb  # noqa: E402

from crawler.db_readiness import (  # noqa: E402
    MIGRATION_ADVISORY_LOCK_KEY,
    is_exact_identity_v4_check,
    is_exact_manifest_source_row_check,
)
from crawler.document_repository import DatabaseConfig, DisclosureDocumentRepository, DocumentPayload  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = PROJECT_ROOT / "database" / "schema"
SCHEMA_PATHS = sorted(SCHEMA_DIR.glob("[0-9][0-9][0-9]_*.sql"))
REQUIRED_TEST_ENV = (
    "RS_TEST_DB_HOST",
    "RS_TEST_DB_PORT",
    "RS_TEST_DB_USER",
    "RS_TEST_DB_PASSWORD",
    "RS_TEST_DB_NAME",
)


@dataclass(frozen=True)
class IntegrationDatabaseConfig:
    host: str
    port: int
    user: str
    password: str
    dbname: str
    sslmode: str | None = None

    def connect_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "dbname": self.dbname,
            "connect_timeout": 10,
            "autocommit": True,
        }
        if self.sslmode:
            kwargs["sslmode"] = self.sslmode
        return kwargs

    def repository_config(self) -> DatabaseConfig:
        return DatabaseConfig(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=self.dbname,
            connect_timeout=10,
            sslmode=self.sslmode,
        )


def _load_test_database_config() -> IntegrationDatabaseConfig | None:
    """환경변수만 읽어 테스트 DB 설정을 반환한다.

    RS_DB_* fallback을 두지 않는 것이 의도적인 안전 계약이다. 환경변수가
    일부만 있으면 접속하지 않고 skip하여 개발자 셸의 부분 설정도 안전하게
    처리한다.
    """

    values = {name: os.environ.get(name, "").strip() for name in REQUIRED_TEST_ENV}
    if not all(values.values()):
        return None
    dbname = values["RS_TEST_DB_NAME"]
    if re.search(r"test", dbname, re.IGNORECASE) is None:
        raise RuntimeError(
            "RS_TEST_DB_NAME에는 안전을 위해 'test'가 포함되어야 합니다: " + dbname
        )
    try:
        port = int(values["RS_TEST_DB_PORT"])
    except ValueError as exc:
        raise RuntimeError("RS_TEST_DB_PORT는 정수여야 합니다") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("RS_TEST_DB_PORT가 유효한 범위를 벗어났습니다")
    return IntegrationDatabaseConfig(
        host=values["RS_TEST_DB_HOST"],
        port=port,
        user=values["RS_TEST_DB_USER"],
        password=values["RS_TEST_DB_PASSWORD"],
        dbname=dbname,
        sslmode=os.environ.get("RS_TEST_DB_SSLMODE", "").strip() or None,
    )


TEST_DB = _load_test_database_config()
pytestmark = pytest.mark.skipif(
    TEST_DB is None,
    reason="RS_TEST_DB_HOST/PORT/USER/PASSWORD/NAME이 모두 있어야 PostgreSQL 통합 테스트를 실행합니다",
)


def _connect(config: IntegrationDatabaseConfig):
    return psycopg.connect(**config.connect_kwargs())


def _table_exists(connection: Any) -> bool:
    row = connection.execute(
        "SELECT to_regclass('public.rs_disclosure_documents')"
    ).fetchone()
    return bool(row and row[0])


def _reset_public_contract(connection: Any) -> None:
    """지정된 disposable test DB의 public 계약만 초기화한다."""

    connection.execute(
        "DROP TABLE IF EXISTS public.rs_disclosure_documents CASCADE"
    )
    connection.execute(
        "DROP FUNCTION IF EXISTS public.set_rs_disclosure_documents_updated_at() CASCADE"
    )


def _apply_schema_chain(connection: Any, *, initialize: bool) -> None:
    """001 최초 생성 후 002~007을 번호순으로 적용한다.

    001은 CREATE TABLE이라 원천적으로 재실행할 수 없으므로, 운영 적용
    도구와 동일하게 이미 테이블이 있으면 건너뛰고 후속 migration만
    재실행한다. 002~007은 각자 멱등 SQL 계약을 직접 검증한다.
    """

    paths = {path.name: path for path in SCHEMA_PATHS}
    if initialize:
        first = paths.get("001_create_rs_disclosure_documents.sql")
        assert first is not None, "001 스키마 파일이 없습니다"
        connection.execute(first.read_text(encoding="utf-8"), prepare=False)
    elif not _table_exists(connection):
        raise AssertionError("재적용 단계에서 rs_disclosure_documents가 없습니다")

    for path in SCHEMA_PATHS:
        if path.name == "001_create_rs_disclosure_documents.sql":
            continue
        connection.execute(path.read_text(encoding="utf-8"), prepare=False)


def _reset_and_apply_through(connection: Any, final_number: int) -> None:
    """통합 테스트 전용으로 001부터 지정 번호까지 깨끗하게 적용한다."""

    _reset_public_contract(connection)
    for path in SCHEMA_PATHS:
        number = int(path.name.split("_", 1)[0])
        if number > final_number:
            break
        connection.execute(path.read_text(encoding="utf-8"), prepare=False)


@pytest.fixture(scope="module")
def test_database() -> IntegrationDatabaseConfig:
    if TEST_DB is None:  # pragma: no cover - pytestmark normally handles this
        pytest.skip("RS_TEST_DB_*가 설정되지 않았습니다")
    connection = _connect(TEST_DB)
    try:
        _reset_public_contract(connection)
        _apply_schema_chain(connection, initialize=True)
        yield TEST_DB
    finally:
        # 테스트가 중간 실패해도 다음 실행은 항상 초기화된 disposable DB에서
        # 시작한다. lock을 보유한 세션은 각 테스트가 finally에서 해제한다.
        try:
            _reset_public_contract(connection)
        finally:
            connection.close()


def test_schema_001_to_007_is_idempotent(test_database: IntegrationDatabaseConfig) -> None:
    """001~007 적용 후 002~007을 다시 적용해도 실패하지 않는다."""

    with _connect(test_database) as connection:
        _apply_schema_chain(connection, initialize=False)
        assert _table_exists(connection)


def test_schema_007_cleans_metadata_without_changing_updated_at(
    test_database: IntegrationDatabaseConfig,
) -> None:
    cleanup = SCHEMA_DIR / "007_cleanup_source_metadata.sql"
    with _connect(test_database) as connection:
        try:
            _reset_and_apply_through(connection, 6)
            connection.execute(
                """
                INSERT INTO public.rs_disclosure_documents
                    (document_key, product_version_key, company_code, company_name,
                     product_name, product_name_normalized, source_metadata)
                VALUES (%s, %s, 'TEST', '테스트', '상품', '상품', %s)
                """,
                (
                    "DOC_0000000091",
                    "PROD_VER_0000000091",
                    Jsonb(
                        {
                            "document_key": "legacy-document-key",
                            "product_version_key": "legacy-product-version-key",
                            "identity_version": 1,
                            "migration": {"source": "manifest.csv", "source_row": 91},
                            "checkpoint_key": "checkpoint-91",
                        }
                    ),
                ),
            )
            before = connection.execute(
                "SELECT source_metadata, updated_at FROM public.rs_disclosure_documents"
            ).fetchone()

            connection.execute(cleanup.read_text(encoding="utf-8"), prepare=False)
            after = connection.execute(
                "SELECT source_metadata, updated_at FROM public.rs_disclosure_documents"
            ).fetchone()

            assert before is not None and after is not None
            assert after[1] == before[1]
            assert after[0]["migration"] == before[0]["migration"]
            assert after[0]["checkpoint_key"] == "checkpoint-91"
            assert not {
                "document_key", "product_version_key", "identity_version"
            } & after[0].keys()
            # 실제 DB에서도 재실행 가능한 migration이어야 한다.
            connection.execute(cleanup.read_text(encoding="utf-8"), prepare=False)
        finally:
            if connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                connection.rollback()
            _reset_and_apply_through(connection, 7)


@pytest.mark.parametrize("case", ["malformed", "duplicate"])
def test_schema_007_preflight_fails_before_mutation(
    test_database: IntegrationDatabaseConfig,
    case: str,
) -> None:
    cleanup = SCHEMA_DIR / "007_cleanup_source_metadata.sql"
    with _connect(test_database) as connection:
        try:
            _reset_and_apply_through(connection, 6)
            metadata_rows = (
                [
                    {"source": "manifest.csv"},
                ]
                if case == "malformed"
                else [
                    {"source": "manifest.csv", "source_row": 77},
                    {"source": "manifest.csv", "source_row": 77},
                ]
            )
            for offset, migration in enumerate(metadata_rows, start=1):
                connection.execute(
                    """
                    INSERT INTO public.rs_disclosure_documents
                        (document_key, product_version_key, company_code, company_name,
                         product_name, product_name_normalized, source_metadata)
                    VALUES (%s, %s, 'TEST', '테스트', '상품', '상품', %s)
                    """,
                    (
                        f"DOC_00000001{offset:02d}",
                        f"PROD_VER_00000001{offset:02d}",
                        Jsonb(
                            {
                                "document_key": "must-remain-after-rollback",
                                "migration": migration,
                            }
                        ),
                    ),
                )

            with pytest.raises(psycopg.errors.RaiseException, match="007 preflight"):
                connection.execute(cleanup.read_text(encoding="utf-8"), prepare=False)
            connection.rollback()
            remaining = connection.execute(
                """
                SELECT COUNT(*)
                FROM public.rs_disclosure_documents
                WHERE source_metadata ? 'document_key'
                """
            ).fetchone()
            assert remaining == (len(metadata_rows),)
        finally:
            if connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                connection.rollback()
            _reset_and_apply_through(connection, 7)


def test_v4_provenance_constraints_and_indexes(test_database: IntegrationDatabaseConfig) -> None:
    with _connect(test_database) as connection:
        constraints = {
            str(row[0]): (str(row[1]), bool(row[2]))
            for row in connection.execute(
                """
                SELECT conname, pg_get_constraintdef(oid), convalidated
                FROM pg_constraint
                WHERE connamespace = 'public'::regnamespace
                  AND conrelid = 'public.rs_disclosure_documents'::regclass
                """
            ).fetchall()
        }
        assert is_exact_identity_v4_check(
            constraints["ck_rs_disclosure_documents_identity_version"][0]
        )
        assert constraints["ck_rs_disclosure_documents_identity_version"][1]
        provenance, provenance_validated = constraints[
            "ck_rs_disclosure_documents_manifest_source_row"
        ]
        assert provenance_validated
        assert is_exact_manifest_source_row_check(provenance)

        indexes = {
            str(row[0]): tuple(bool(value) for value in row[1:4])
            for row in connection.execute(
                """
                SELECT c.relname, i.indisunique, i.indisvalid, i.indisready
                FROM pg_index AS i
                JOIN pg_class AS c ON c.oid = i.indexrelid
                JOIN pg_class AS t ON t.oid = i.indrelid
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND t.relname = 'rs_disclosure_documents'
                """
            ).fetchall()
        }
        assert all(indexes["uq_rs_disclosure_documents_manifest_source_row"])
        assert "ix_rs_disclosure_documents_sha256" in indexes
        assert connection.execute(
            "SELECT to_regclass('public.rs_crawler_control')"
        ).fetchone()[0] is None

        # 007의 provenance CHECK는 0/음수/비숫자 source_row를 차단한다.
        insert_sql = """
            INSERT INTO public.rs_disclosure_documents
                (document_key, product_version_key, company_code, company_name,
                 product_name, product_name_normalized, source_metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        valid_metadata = {"migration": {"source": "manifest.csv", "source_row": "1"}}
        connection.execute(
            insert_sql,
            (
                "DOC_0000000001",
                "PROD_VER_0000000001",
                "TEST",
                "테스트",
                "상품",
                "상품",
                Jsonb(valid_metadata),
            ),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                insert_sql,
                (
                    "DOC_0000000002",
                    "PROD_VER_0000000002",
                    "TEST",
                    "테스트",
                    "상품",
                    "상품",
                    Jsonb(
                        {"migration": {"source": "manifest.csv", "source_row": "0"}}
                    ),
                ),
            )
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                insert_sql,
                (
                    "DOC_0000000003",
                    "PROD_VER_0000000003",
                    "TEST",
                    "테스트",
                    "상품",
                    "상품",
                    Jsonb(valid_metadata),
                ),
            )


def test_repository_preserves_jsonb_provenance(test_database: IntegrationDatabaseConfig) -> None:
    config = test_database.repository_config()
    first_seen = datetime(2026, 1, 1, tzinfo=timezone.utc)
    later_seen = datetime(2026, 1, 2, tzinfo=timezone.utc)
    first = DocumentPayload(
        document_key="DOC_0000000011",
        product_version_key="PROD_VER_0000000011",
        company_code="TEST",
        company_name="테스트",
        product_name="상품",
        product_name_normalized="상품",
        source_product_id="source-product-11",
        document_type="POLICY",
        document_date=date(2026, 1, 1),
        last_attempt_at=first_seen,
        last_seen_at=first_seen,
        source_metadata={
            "migration": {"source": "manifest.csv", "source_row": "11"},
            "checkpoint_key": "legacy-checkpoint-11",
            "source_locator": "locator-11",
            "document_key": "must-be-removed",
            "product_version_key": "must-be-removed",
            "identity_version": 4,
            "final_url": "https://example.test/old",
        },
    )
    second = DocumentPayload(
        **{
            **first.__dict__,
            "last_attempt_at": later_seen,
            "last_seen_at": later_seen,
            "source_metadata": {
                "migration": {"source": "manifest.csv", "source_row": "999"},
                # checkpoint/source locator는 document identity 문맥이므로 같은
                # key의 후속 runtime 이벤트에서도 바뀌면 안 된다.
                "checkpoint_key": "legacy-checkpoint-11",
                "source_locator": "locator-11",
                "final_url": "https://example.test/new",
            },
        }
    )

    repository = DisclosureDocumentRepository(config)
    try:
        repository.upsert_result(first)
        repository.upsert_result(second)
    finally:
        repository.close()

    with _connect(test_database) as connection:
        row = connection.execute(
            """
            SELECT source_metadata, identity_version
            FROM public.rs_disclosure_documents
            WHERE document_key = %s
            """,
            (first.document_key,),
        ).fetchone()
        assert row is not None
        metadata, identity_version = row
        assert identity_version == 4
        assert metadata["migration"]["source_row"] == "11"
        assert metadata["checkpoint_key"] == "legacy-checkpoint-11"
        assert metadata["source_locator"] == "locator-11"
        assert metadata["final_url"] == "https://example.test/new"
        assert "document_key" not in metadata
        assert "product_version_key" not in metadata
        assert "identity_version" not in metadata


def test_advisory_shared_and_exclusive_locks_are_mutually_exclusive(
    test_database: IntegrationDatabaseConfig,
) -> None:
    shared = _connect(test_database)
    exclusive = _connect(test_database)
    try:
        assert shared.execute(
            "SELECT pg_try_advisory_lock_shared(%s)",
            (MIGRATION_ADVISORY_LOCK_KEY,),
        ).fetchone()[0]
        assert not exclusive.execute(
            "SELECT pg_try_advisory_lock(%s)",
            (MIGRATION_ADVISORY_LOCK_KEY,),
        ).fetchone()[0]

        assert shared.execute(
            "SELECT pg_advisory_unlock_shared(%s)",
            (MIGRATION_ADVISORY_LOCK_KEY,),
        ).fetchone()[0]
        assert exclusive.execute(
            "SELECT pg_try_advisory_lock(%s)",
            (MIGRATION_ADVISORY_LOCK_KEY,),
        ).fetchone()[0]
        assert not shared.execute(
            "SELECT pg_try_advisory_lock_shared(%s)",
            (MIGRATION_ADVISORY_LOCK_KEY,),
        ).fetchone()[0]
    finally:
        try:
            exclusive.execute(
                "SELECT pg_advisory_unlock(%s)",
                (MIGRATION_ADVISORY_LOCK_KEY,),
            )
        finally:
            shared.close()
            exclusive.close()
