from pathlib import Path

import pytest

from crawler.db_readiness import (
    DBReadinessChecker,
    DBReadinessError,
    REQUIRED_COLUMNS,
    SUPPORTED_IDENTITY_VERSIONS,
    is_exact_manifest_source_row_check,
)


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows if isinstance(self.rows, list) else [self.rows]

    def fetchone(self):
        return self.rows[0] if isinstance(self.rows, list) and self.rows else self.rows


class Connection:
    def __init__(
        self,
        *,
        invalid=0,
        document_length=14,
        product_length=19,
        identity_default="4",
        identity_constraint="CHECK ((identity_version = 4))",
        provenance_constraint="CHECK (source_metadata->'migration'->>'source' IS DISTINCT FROM 'manifest.csv' OR COALESCE(source_metadata->'migration'->>'source_row' ~ '^[1-9][0-9]*$', FALSE))",
        provenance_validated=True,
        provenance_index=(True, True, True),
        invalid_provenance=0,
        forbidden_metadata=0,
    ):
        self.invalid = invalid
        self.document_length = document_length
        self.product_length = product_length
        self.identity_default = identity_default
        self.identity_constraint = identity_constraint
        self.provenance_constraint = provenance_constraint
        self.provenance_validated = provenance_validated
        self.provenance_index = provenance_index
        self.invalid_provenance = invalid_provenance
        self.forbidden_metadata = forbidden_metadata
        self.queries = []

    def execute(self, query, params=()):
        self.queries.append(query)
        if "SELECT 1" in query:
            return Cursor([(1,)])
        if "character_maximum_length" in query:
            return Cursor([
                {"column_name": "document_key", "character_maximum_length": self.document_length},
                {"column_name": "product_version_key", "character_maximum_length": self.product_length},
            ])
        if "information_schema.columns" in query and "identity_version" not in query:
            return Cursor([(name,) for name in REQUIRED_COLUMNS])
        if "information_schema.columns" in query:
            return Cursor([{"column_default": self.identity_default, "is_nullable": "NO"}])
        if "invalid_provenance_count" in query:
            return Cursor([{"invalid_provenance_count": self.invalid_provenance}])
        if "forbidden_metadata_count" in query:
            return Cursor([{"forbidden_metadata_count": self.forbidden_metadata}])
        if "invalid_key_count" in query:
            return Cursor([{"invalid_key_count": self.invalid}])
        if "invalid_identity_count" in query:
            return Cursor([{"invalid_identity_count": self.invalid}])
        if "pg_get_constraintdef" in query:
            if "manifest_source_row" in query:
                rows = [] if self.provenance_constraint is None else [{
                    "definition": self.provenance_constraint,
                    "convalidated": self.provenance_validated,
                }]
            else:
                rows = [] if self.identity_constraint is None else [{"definition": self.identity_constraint}]
            return Cursor(rows)
        if "indisunique" in query:
            return Cursor([self.provenance_index])
        if "has_table_privilege" in query:
            return Cursor([{"can_select": True, "can_insert": True, "can_update": True}])
        if "pg_try_advisory_lock_shared" in query:
            return Cursor([{"acquired": True}])
        return Cursor([(True,)])


class Repository:
    def __init__(self, connection):
        self.connection = connection


def ready_checker(tmp_path: Path, connection: Connection):
    return DBReadinessChecker(
        Repository(connection),
        outbox_paths=[tmp_path / "DB.jsonl"],
    )


def test_readiness_allows_v4_rows_and_uses_shared_lock(tmp_path):
    checker = ready_checker(tmp_path, Connection(invalid=0))
    result = checker.ensure()
    assert result.ready
    assert any("pg_try_advisory_lock_shared" in query for query in checker.repository.connection.queries)


def test_hold_migration_lock_acquired_once_until_release(tmp_path):
    checker = ready_checker(tmp_path, Connection(invalid=0))

    result = checker.ensure(hold_migration_lock=True)
    assert result.ready
    queries = checker.repository.connection.queries
    assert sum("pg_try_advisory_lock_shared" in query for query in queries) == 1
    assert not any("pg_advisory_unlock_shared" in query for query in queries)
    assert checker.migration_lock_held

    checker.release_migration_lock()
    assert sum("pg_advisory_unlock_shared" in query for query in queries) == 1
    assert not checker.migration_lock_held


def test_readiness_only_supports_current_v4():
    assert SUPPORTED_IDENTITY_VERSIONS == {4}


def test_readiness_blocks_pre_cutover_key_column_lengths(tmp_path):
    checker = ready_checker(tmp_path, Connection(document_length=10, product_length=10))
    with pytest.raises(DBReadinessError, match="identity key 형식"):
        checker.ensure()


def test_readiness_blocks_pre_cutover_identity_default(tmp_path):
    checker = ready_checker(tmp_path, Connection(identity_default="3"))
    with pytest.raises(DBReadinessError, match="identity version"):
        checker.ensure()


def test_readiness_rejects_similar_but_wrong_identity_default(tmp_path):
    checker = ready_checker(tmp_path, Connection(identity_default="14"))
    with pytest.raises(DBReadinessError, match="identity version"):
        checker.ensure()


def test_readiness_blocks_unsupported_identity_version(tmp_path):
    checker = ready_checker(tmp_path, Connection(invalid=1))
    with pytest.raises(DBReadinessError, match="identity version"):
        checker.ensure()


def test_readiness_requires_identity_v4_check_constraint(tmp_path):
    checker = ready_checker(tmp_path, Connection(identity_constraint=None))
    with pytest.raises(DBReadinessError, match="identity version"):
        checker.ensure()


def test_readiness_requires_exact_manifest_provenance_contract(tmp_path):
    checker = ready_checker(
        tmp_path,
        Connection(provenance_constraint="CHECK (TRUE)"),
    )
    with pytest.raises(DBReadinessError, match="manifest provenance"):
        checker.ensure()


def test_readiness_requires_validated_manifest_provenance_check(tmp_path):
    checker = ready_checker(tmp_path, Connection(provenance_validated=False))
    with pytest.raises(DBReadinessError, match="manifest provenance"):
        checker.ensure()


def test_readiness_requires_valid_manifest_unique_index(tmp_path):
    checker = ready_checker(tmp_path, Connection(provenance_index=(True, False, True)))
    with pytest.raises(DBReadinessError, match="manifest provenance"):
        checker.ensure()


def test_readiness_rejects_forbidden_identity_metadata(tmp_path):
    checker = ready_checker(tmp_path, Connection(forbidden_metadata=1))
    with pytest.raises(DBReadinessError, match="manifest provenance"):
        checker.ensure()


def test_manifest_provenance_canonical_parser_rejects_extra_condition():
    valid = "CHECK (((source_metadata -> 'migration'::text) ->> 'source'::text IS DISTINCT FROM 'manifest.csv'::text OR COALESCE((((source_metadata -> 'migration'::text) ->> 'source_row'::text) ~ '^[1-9][0-9]*$'::text), false)))"
    assert is_exact_manifest_source_row_check(valid)
    assert not is_exact_manifest_source_row_check(valid[:-1] + " AND TRUE)")


@pytest.mark.parametrize("constraint", ["CHECK ((identity_version = 14))", "CHECK ((identity_version = 40))"])
def test_readiness_rejects_similar_identity_v4_check_constraints(tmp_path, constraint):
    checker = ready_checker(tmp_path, Connection(identity_constraint=constraint))
    with pytest.raises(DBReadinessError, match="identity version"):
        checker.ensure()


def test_readiness_blocks_corrupt_outbox(tmp_path):
    checker = ready_checker(tmp_path, Connection())
    (tmp_path / "DB.jsonl").write_text('{not-json}\n', encoding="utf-8")
    with pytest.raises(DBReadinessError, match="outbox"):
        checker.ensure()
