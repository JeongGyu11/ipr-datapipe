import re
from datetime import datetime, timezone

import pytest

from crawler.document_repository import (
    DatabaseConfig,
    DocumentPayload,
    DisclosureDocumentRepository,
    IdentityKeyCollisionError,
)


class _Tx:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _Cursor:
    rowcount = 1

    def __init__(self, *, rowcount=1):
        self.rowcount = rowcount
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self


def _payload(**overrides):
    values = dict(
        document_key="DOC_0aB1cD2eF3",
        product_version_key="PROD_VER_9zY8xW7vU6",
        company_code="DB",
        company_name="DB손해보험",
        product_name="상품",
        product_name_normalized="상품",
        last_attempt_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    values.update(overrides)
    return DocumentPayload(**values)


def test_repository_accepts_prefixed_base62_ten_character_keys():
    connection = _Cursor()
    connection.transaction = lambda: _Tx()
    repository = DisclosureDocumentRepository(
        DatabaseConfig("host", 5432, "user", "password", "db"),
        connection_factory=lambda **_: connection,
    )

    repository.upsert_result(_payload())

    sql = re.sub(r"\s+", " ", connection.calls[-1][0]).strip()
    assert "WHERE rs.product_version_key IS NOT DISTINCT FROM EXCLUDED.product_version_key" in sql
    assert "NULLIF(rs.source_metadata->>'checkpoint_key', '')" in sql
    assert "NULLIF(rs.source_metadata->>'source_locator', '')" in sql
    assert "NULLIF(rs.document_url, '')" in sql
    assert "NULLIF(rs.original_filename, '')" in sql
    assert "RETURNING rs.document_key" in sql


@pytest.mark.parametrize(
    ("document_key", "product_version_key"),
    [
        ("0aB1cD2eF3", "9zY8xW7vU6"),
        ("0aB1cD2eF3", "PROD_VER_9zY8xW7vU6"),
        ("DOC_0aB1cD2eF3", "9zY8xW7vU6"),
        ("DOC_0aB1cD2eF3", "PROD_VER_9zY8xW7vU"),
        ("DOC_0aB1cD2eF3", "DOC_9zY8xW7vU6"),
    ],
)
def test_repository_rejects_invalid_prefixed_key_pair(document_key, product_version_key):
    connection = _Cursor()
    connection.transaction = lambda: _Tx()
    repository = DisclosureDocumentRepository(
        DatabaseConfig("host", 5432, "user", "password", "db"),
        connection_factory=lambda **_: connection,
    )

    with pytest.raises(ValueError, match="key"):
        repository.upsert_result(_payload(document_key=document_key, product_version_key=product_version_key))
    assert connection.calls == []


def test_repository_rejects_legacy_sha256_key_pair_after_cutover():
    connection = _Cursor()
    connection.transaction = lambda: _Tx()
    repository = DisclosureDocumentRepository(
        DatabaseConfig("host", 5432, "user", "password", "db"),
        connection_factory=lambda **_: connection,
    )

    with pytest.raises(ValueError, match="DOC_"):
        repository.upsert_result(_payload(document_key="a" * 64, product_version_key="b" * 64))
    assert connection.calls == []


@pytest.mark.parametrize("identity_version", [1, 2, 3, 5])
def test_repository_rejects_non_current_identity_version(identity_version):
    connection = _Cursor()
    connection.transaction = lambda: _Tx()
    repository = DisclosureDocumentRepository(
        DatabaseConfig("host", 5432, "user", "password", "db"),
        connection_factory=lambda **_: connection,
    )

    with pytest.raises(ValueError, match="identity_version"):
        repository.upsert_result(_payload(identity_version=identity_version))
    assert connection.calls == []


def test_repository_rejects_mixed_key_formats_before_db_call():
    connection = _Cursor()
    connection.transaction = lambda: _Tx()
    repository = DisclosureDocumentRepository(
        DatabaseConfig("host", 5432, "user", "password", "db"),
        connection_factory=lambda **_: connection,
    )

    with pytest.raises(ValueError, match="product_version_key"):
        repository.upsert_result(_payload(product_version_key="b" * 64))
    assert connection.calls == []


def test_repository_fails_closed_when_key_conflicts_with_other_identity():
    connection = _Cursor(rowcount=0)
    connection.transaction = lambda: _Tx()
    repository = DisclosureDocumentRepository(
        DatabaseConfig("host", 5432, "user", "password", "db"),
        connection_factory=lambda **_: connection,
    )

    with pytest.raises(IdentityKeyCollisionError, match="document_key 충돌"):
        repository.upsert_result(_payload())
