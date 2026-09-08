"""상품공시 문서 DB의 비민감 운영 상태를 읽기 전용으로 출력한다."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crawler.document_repository import DatabaseConfig  # noqa: E402


def inspect(connection) -> dict:
    tables = connection.execute(
        """
        SELECT to_regclass('public.rs_disclosure_documents')::text AS documents
        """
    ).fetchone()
    result: dict = {"tables": dict(tables or {})}
    if result["tables"].get("documents"):
        result["documents"] = dict(
            connection.execute(
                """
                SELECT COUNT(*) AS row_count,
                       COUNT(*) FILTER (WHERE identity_version = 4) AS identity_v4,
                       COUNT(*) FILTER (WHERE identity_version IS NULL
                                             OR identity_version <> 4) AS identity_unsupported,
                       COUNT(*) FILTER (WHERE document_key !~ '^DOC_[0-9A-Za-z]{10}$'
                                             OR product_version_key !~ '^PROD_VER_[0-9A-Za-z]{10}$') AS invalid_identity_key_count,
                       COUNT(*) FILTER (WHERE sha256 IS NOT NULL
                                             AND sha256 !~ '^[0-9a-f]{64}$') AS invalid_sha256_count,
                       COUNT(*) FILTER (WHERE file_status = 'AVAILABLE'
                                             AND (sha256 IS NULL OR sha256 !~ '^[0-9a-f]{64}$')) AS available_without_valid_sha256,
                       MIN(created_at) AS first_created_at,
                       MAX(updated_at) AS last_updated_at
                FROM rs_disclosure_documents
                """
            ).fetchone()
        )
        result["company_counts"] = list(
            connection.execute(
                """
                SELECT company_code, COUNT(*) AS row_count
                FROM rs_disclosure_documents
                GROUP BY company_code ORDER BY company_code
                """
            ).fetchall()
        )
        result["file_status_counts"] = list(
            connection.execute(
                """
                SELECT file_status, COALESCE(last_attempt_status, 'NONE') AS last_attempt_status,
                       COUNT(*) AS row_count
                FROM rs_disclosure_documents
                GROUP BY file_status, COALESCE(last_attempt_status, 'NONE')
                ORDER BY file_status, last_attempt_status
                """
            ).fetchall()
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    config = DatabaseConfig.from_env()
    with psycopg.connect(
        **config.connect_kwargs(),
        row_factory=dict_row,
    ) as connection:
        payload = inspect(connection)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
