from pathlib import Path

import pytest

from scripts import apply_database_schema as schema


def test_parse_integer_default_accepts_exact_postgresql_integer_forms() -> None:
    assert schema._parse_integer_default("4") == 4
    assert schema._parse_integer_default("4::smallint") == 4
    assert schema._parse_integer_default("(4)::integer") == 4


def test_parse_integer_default_does_not_accept_values_containing_four() -> None:
    assert schema._parse_integer_default("14") == 14
    assert schema._parse_integer_default("40::smallint") == 40
    assert schema._parse_integer_default("nextval('seq4')") is None


def test_load_db_config_uses_database_config_contract(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "RS_DB_HOST=db.example",
                "RS_DB_PORT=5433",
                "RS_DB_USER=app",
                "RS_DB_PASSWORD=secret",
                "RS_DB_NAME=ipr",
                "RS_DB_SSLMODE=require",
                "RS_DB_CONNECT_TIMEOUT=27",
            ]
        ),
        encoding="utf-8",
    )
    for key in (
        "RS_DB_HOST",
        "RS_DB_PORT",
        "RS_DB_USER",
        "RS_DB_PASSWORD",
        "RS_DB_NAME",
        "RS_DB_SSLMODE",
        "RS_DB_CONNECT_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)

    config = schema.load_db_config(env_file)

    assert config == {
        "host": "db.example",
        "port": 5433,
        "user": "app",
        "password": "secret",
        "dbname": "ipr",
        "connect_timeout": 27,
        "sslmode": "require",
        "autocommit": True,
    }


def test_load_db_config_rejects_missing_env_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        schema.load_db_config(tmp_path / "missing.env")


def test_final_schema_enforces_identity_v4() -> None:
    project_root = Path(schema.PROJECT_ROOT)
    create_sql = (
        project_root / "database" / "schema" / "001_create_rs_disclosure_documents.sql"
    ).read_text(encoding="utf-8")
    migration_sql = (
        project_root / "database" / "schema" / "006_enforce_identity_version_v4.sql"
    ).read_text(encoding="utf-8")

    for sql in (create_sql, migration_sql):
        assert "ck_rs_disclosure_documents_identity_version" in sql
        assert "identity_version = 4" in sql


def test_source_metadata_cleanup_preserves_provenance_and_updated_at() -> None:
    project_root = Path(schema.PROJECT_ROOT)
    cleanup_sql = (
        project_root / "database" / "schema" / "007_cleanup_source_metadata.sql"
    ).read_text(encoding="utf-8")

    assert "source_metadata - ARRAY[" in cleanup_sql
    for field in ("document_key", "product_version_key", "identity_version"):
        assert f"'{field}'" in cleanup_sql
    assert "DISABLE TRIGGER trg_rs_disclosure_documents_updated_at" in cleanup_sql
    assert "ENABLE TRIGGER trg_rs_disclosure_documents_updated_at" in cleanup_sql
    assert "source_metadata->'migration'->>'source_row' ~ '^[1-9][0-9]*$'" in cleanup_sql
    assert "COALESCE(" in cleanup_sql
    assert "ck_rs_disclosure_documents_manifest_source_row" in cleanup_sql
    assert "uq_rs_disclosure_documents_manifest_source_row" in cleanup_sql
    assert "CREATE TABLE rs_crawler_control" not in cleanup_sql
    assert "malformed_count" in cleanup_sql
    assert "duplicate_count" in cleanup_sql
    assert "trigger 비활성화 권한" in cleanup_sql


def test_manifest_provenance_schema_contract_is_verified_exactly() -> None:
    source = Path(schema.PROJECT_ROOT / "scripts" / "apply_database_schema.py").read_text(
        encoding="utf-8"
    )
    assert "is_exact_manifest_source_row_check" in source
    assert "convalidated" in source
    assert "indisvalid" in source
    assert "indisready" in source
    assert "source_metadata ?| ARRAY" in source
