"""수집 시작 전 DB runtime readiness 검사.

이 검사는 회사 lock을 잡거나 웹 adapter를 호출하기 전에 한 번만 수행한다.
조회/잠금 확인만 하며 schema migration이나 데이터 변경을 수행하지 않는다.
마이그레이션 도구와 동일한 advisory-lock 키를 사용하므로 migration 중에는
수집을 시작하지 않는다.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from crawler.document_identity import IDENTITY_VERSION
from crawler.db_outbox import DatabaseOutbox

DB_TABLE = "rs_disclosure_documents"
# Runtime starts only after the explicit identity migration has completed.
# Historical versions remain supported by migration/archive tools, not by the
# live crawler.  Keeping this set narrow prevents a stale bridge from writing
# a row that the current key contract cannot reproduce.
SUPPORTED_IDENTITY_VERSIONS = frozenset({IDENTITY_VERSION})
# schema 적용 작업과 공유하는 migration advisory-lock 키.
MIGRATION_ADVISORY_LOCK_KEY = 7_218_453_911_204_731
REQUIRED_COLUMNS = frozenset(
    {
        "document_key",
        "product_version_key",
        "collector_type",
        "company_code",
        "company_name",
        "product_name",
        "product_name_normalized",
        "sale_status",
        "document_type",
        "source_metadata",
        "file_status",
        "last_attempt_status",
        "last_seen_run_id",
        "last_download_run_id",
        "last_status_run_id",
        "last_seen_at",
        "last_attempt_at",
        "identity_version",
    }
)


@dataclass
class DBReadinessResult:
    ready: bool
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "checks": dict(self.checks), "errors": list(self.errors)}


class DBReadinessError(RuntimeError):
    def __init__(self, result: DBReadinessResult):
        self.result = result
        detail = "; ".join(result.errors) or "DB runtime readiness 검사 실패"
        super().__init__(detail)


def _rows(result: Any) -> list[Any]:
    if result is None:
        return []
    fetchall = getattr(result, "fetchall", None)
    if callable(fetchall):
        return list(fetchall())
    if isinstance(result, (list, tuple)):
        return list(result)
    return [result]


def _first_value(row: Any, key: str | None = None) -> Any:
    if isinstance(row, Mapping):
        if key is not None and key in row:
            return row[key]
        return next(iter(row.values()), None)
    if isinstance(row, (tuple, list)):
        return row[0] if row else None
    return row


def _exact_integer_default(value: Any) -> int | None:
    """Parse a PostgreSQL scalar default without substring false positives."""
    text = str(value or "").strip()
    match = re.fullmatch(r"\(?\s*([+-]?\d+)\s*\)?(?:\s*::[A-Za-z_][A-Za-z0-9_]*)?", text)
    return int(match.group(1)) if match else None


def parse_postgres_integer_default(value: Any) -> int | None:
    """PostgreSQL 정수 DEFAULT를 정확히 해석하는 공용 parser.

    readiness와 schema 적용 도구가 ``14``를 ``4``로 오인하는 식의
    substring 검사를 하지 않도록 같은 규칙을 공유한다.
    """

    return _exact_integer_default(value)


def is_exact_identity_v4_check(definition: Any) -> bool:
    """제약조건 정의가 ``identity_version = 4`` 하나만 포함하는지 검증한다.

    PostgreSQL의 ``pg_get_constraintdef``는 CHECK 식을 여러 겹의 괄호로
    감쌀 수 있다. 괄호를 벗긴 뒤 전체 식을 비교하므로 ``= 40``, ``IN
    (4)``, ``= 4 OR ...`` 같은 유사 식은 허용하지 않는다.
    """

    text = re.sub(r"\s+", " ", str(definition or "").strip())
    text = re.sub(r"^CHECK\s*", "", text, flags=re.IGNORECASE)
    # pg_get_constraintdef may emit CHECK (((identity_version = 4))).
    while text.startswith("(") and text.endswith(")"):
        depth = 0
        wraps_entire_expression = True
        for index, char in enumerate(text):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index != len(text) - 1:
                    wraps_entire_expression = False
                    break
                if depth < 0:
                    wraps_entire_expression = False
                    break
        if not wraps_entire_expression or depth != 0:
            break
        text = text[1:-1].strip()
    return bool(
        re.fullmatch(
            r"(?:\"?identity_version\"?)\s*=\s*4(?:\s*::[A-Za-z_][A-Za-z0-9_]*)?",
            text,
            flags=re.IGNORECASE,
        )
    )


def _canonical_sql_expression(definition: Any) -> str:
    """정해진 CHECK 식 비교를 위한 PostgreSQL expression 정규화.

    ``pg_get_constraintdef``는 버전마다 괄호, 공백, ``::text`` cast를
    다르게 출력할 수 있으므로 표현식의 의미에 영향을 주지 않는 표기만
    제거한다. 식 자체의 토큰은 그대로 남겨서 다른 조건이 몰래 붙은
    CHECK를 허용하지 않는다.
    """

    text = str(definition or "").strip().lower()
    text = re.sub(r"^check\s*", "", text)
    text = re.sub(r"::[a-z_][a-z0-9_]*(?:\s+)?", "", text)
    text = re.sub(r"[\s\"\n\r\t]", "", text)
    return text.replace("(", "").replace(")", "")


def is_exact_manifest_source_row_check(definition: Any) -> bool:
    """manifest.csv provenance CHECK가 canonical 식과 정확히 같은지 검증."""

    expected = (
        "source_metadata->'migration'->>'source'"
        "isdistinctfrom'manifest.csv'"
        "orcoalesce(source_metadata->'migration'->>'source_row'"
        "~'^[1-9][0-9]*$',false)"
    )
    return _canonical_sql_expression(definition) == _canonical_sql_expression(expected)


class DBReadinessChecker:
    """repository connection과 로컬 outbox를 검사하는 checker."""

    def __init__(
        self,
        repository: Any,
        *,
        outbox_dirs: Iterable[str | Path] = (),
        outbox_paths: Iterable[str | Path] = (),
        table_name: str = DB_TABLE,
        identity_version: int = IDENTITY_VERSION,
        advisory_lock_key: int = MIGRATION_ADVISORY_LOCK_KEY,
    ) -> None:
        if not table_name.replace("_", "").isalnum():
            raise ValueError("안전하지 않은 readiness table 이름")
        self.repository = repository
        self.outbox_dirs = [Path(path) for path in outbox_dirs]
        self.outbox_paths = [Path(path) for path in outbox_paths]
        self.table_name = table_name
        self.identity_version = int(identity_version)
        self.advisory_lock_key = int(advisory_lock_key)
        self._guard_connection: Any | None = None

    @property
    def migration_lock_held(self) -> bool:
        """이번 readiness 실행에서 shared migration lock을 보유 중인지."""

        return self._guard_connection is not None

    @property
    def connection(self) -> Any:
        connection = getattr(self.repository, "connection", None)
        if callable(connection):
            return connection()
        if connection is None:
            raise RuntimeError("repository에 DB connection이 없습니다")
        return connection

    def _execute(self, connection: Any, query: str, params: tuple[Any, ...] = ()) -> Any:
        execute = getattr(connection, "execute", None)
        if not callable(execute):
            raise RuntimeError("DB connection에 execute가 없습니다")
        return execute(query, params)

    def check(self) -> DBReadinessResult:
        result = DBReadinessResult(ready=False)
        owns_lock = False
        # 직접 check()를 호출하는 운영 도구도 검사 전체를 migration과
        # 격리한다. ensure(hold_migration_lock=True)는 호출자가 이미 잡은
        # 동일 connection의 lock을 검사와 수집 종료까지 유지한다.
        try:
            # repository가 connection factory를 노출하는 경우에도 lock을
            # 획득한 session과 동일한 connection에서 모든 검사를 수행한다.
            connection = self._guard_connection or self.connection
            if not self.migration_lock_held:
                if not self._acquire_migration_lock(connection):
                    result.checks["migration_advisory_lock"] = False
                    result.errors.append("migration advisory lock이 사용 중입니다")
                    return result
                owns_lock = True
            else:
                # lock 획득은 ensure()에서 정확히 한 번만 수행한다.
                result.checks["migration_advisory_lock"] = True
        except Exception as exc:
            result.checks["migration_advisory_lock"] = False
            result.errors.append(f"migration advisory lock: {type(exc).__name__}: {exc}")
            return result
        try:
            probe = self._execute(connection, "SELECT 1")
            fetchone = getattr(probe, "fetchone", None)
            if callable(fetchone):
                fetchone()
            result.checks["database_connection"] = True
        except Exception as exc:
            result.errors.append(f"DB 연결: {type(exc).__name__}: {exc}")
            result.checks["database_connection"] = False
            if owns_lock:
                self.release_migration_lock()
            return result

        try:
            rows = _rows(
                self._execute(
                    connection,
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = %s
                    """,
                    (self.table_name,),
                )
            )
            columns = {
                str(_first_value(row, "column_name"))
                for row in rows
                if _first_value(row, "column_name") is not None
            }
            missing = sorted(REQUIRED_COLUMNS - columns)
            if missing:
                raise RuntimeError(f"필수 column 누락: {', '.join(missing)}")
            result.checks["schema_columns"] = True
        except Exception as exc:
            result.checks["schema_columns"] = False
            result.errors.append(f"필수 schema/column: {type(exc).__name__}: {exc}")

        try:
            rows = _rows(
                self._execute(
                    connection,
                    """
                    SELECT column_name, character_maximum_length
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = %s
                      AND column_name IN ('document_key', 'product_version_key')
                    """,
                    (self.table_name,),
                )
            )
            lengths = {
                str(_first_value(row, "column_name")): (
                    row.get("character_maximum_length")
                    if isinstance(row, Mapping)
                    else (row[1] if isinstance(row, (tuple, list)) and len(row) > 1 else None)
                )
                for row in rows
            }
            expected_lengths = {"document_key": 14, "product_version_key": 19}
            if any(lengths.get(name) != expected for name, expected in expected_lengths.items()):
                raise RuntimeError(
                    "접두사 key column 길이 불일치: "
                    + ", ".join(f"{name}={lengths.get(name)} (expected {expected})" for name, expected in expected_lengths.items())
                )
            invalid = _rows(
                self._execute(
                    connection,
                    f"""
                    SELECT COUNT(*) AS invalid_key_count
                    FROM {self.table_name}
                    WHERE document_key !~ '^DOC_[0-9A-Za-z]{{10}}$'
                       OR product_version_key !~ '^PROD_VER_[0-9A-Za-z]{{10}}$'
                    """,
                )
            )
            value = _first_value(invalid[0], "invalid_key_count") if invalid else None
            if value is None or int(value) != 0:
                raise RuntimeError(f"접두사 key 형식 불일치 행이 있습니다: {value}")
            result.checks["identity_key_format"] = True
        except Exception as exc:
            result.checks["identity_key_format"] = False
            result.errors.append(f"identity key 형식: {type(exc).__name__}: {exc}")

        try:
            rows = _rows(
                self._execute(
                    connection,
                    """
                    SELECT column_default, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = %s AND column_name = 'identity_version'
                    """,
                    (self.table_name,),
                )
            )
            if not rows:
                raise RuntimeError("identity_version column을 확인할 수 없습니다")
            version_row = rows[0]
            column_default = _first_value(version_row, "column_default")
            is_nullable = (
                version_row.get("is_nullable")
                if isinstance(version_row, Mapping)
                else (version_row[1] if isinstance(version_row, (tuple, list)) and len(version_row) > 1 else None)
            )
            if _exact_integer_default(column_default) != self.identity_version:
                raise RuntimeError(
                    f"identity_version 기본값이 {self.identity_version}이 아닙니다: {column_default}"
                )
            if str(is_nullable or "").upper() != "NO":
                raise RuntimeError("identity_version은 NOT NULL이어야 합니다")
            supported_versions = sorted(SUPPORTED_IDENTITY_VERSIONS)
            version_placeholders = ", ".join(["%s"] * len(supported_versions))
            max_row = _rows(
                self._execute(
                    connection,
                    f"""
                    SELECT COUNT(*) AS invalid_identity_count
                    FROM {self.table_name}
                    WHERE identity_version IS NULL OR identity_version NOT IN ({version_placeholders})
                    """,
                    tuple(supported_versions),
                )
            )
            value = _first_value(max_row[0], "invalid_identity_count") if max_row else None
            if value is None or int(value) != 0:
                raise RuntimeError(f"identity version 불일치 행이 있습니다: {value}")
            constraint_rows = _rows(
                self._execute(
                    connection,
                    """
                    SELECT pg_get_constraintdef(oid) AS definition
                    FROM pg_constraint
                    WHERE connamespace = current_schema()::regnamespace
                      AND conrelid = %s::regclass
                      AND conname = 'ck_rs_disclosure_documents_identity_version'
                    """,
                    (self.table_name,),
                )
            )
            definition = (
                str(_first_value(constraint_rows[0], "definition") or "")
                if constraint_rows
                else ""
            )
            if not is_exact_identity_v4_check(definition):
                raise RuntimeError(
                    "identity_version=4 CHECK가 없거나 잘못됐습니다: " + definition
                )
            result.checks["identity_version"] = True
        except Exception as exc:
            result.checks["identity_version"] = False
            result.errors.append(f"identity version: {type(exc).__name__}: {exc}")

        # 007 migration이 보장하는 provenance 계약을 런타임에서도 확인한다.
        # CHECK가 아직 NOT VALID이거나 unique index가 invalid/작성 중이면
        # source_row의 중복을 신뢰할 수 없으므로 수집을 시작하지 않는다.
        try:
            constraint_rows = _rows(
                self._execute(
                    connection,
                    """
                    SELECT pg_get_constraintdef(oid) AS definition,
                           convalidated
                    FROM pg_constraint
                    WHERE connamespace = current_schema()::regnamespace
                      AND conrelid = %s::regclass
                      AND conname = 'ck_rs_disclosure_documents_manifest_source_row'
                    """,
                    (self.table_name,),
                )
            )
            if not constraint_rows:
                raise RuntimeError("manifest source_row CHECK가 없습니다")
            row = constraint_rows[0]
            definition = _first_value(row, "definition")
            validated = (
                row.get("convalidated")
                if isinstance(row, Mapping)
                else (row[1] if isinstance(row, (tuple, list)) and len(row) > 1 else None)
            )
            if not bool(validated) or not is_exact_manifest_source_row_check(definition):
                raise RuntimeError(
                    "manifest source_row CHECK가 canonical 식이 아니거나 NOT VALID입니다: "
                    f"definition={definition!s}, convalidated={validated!r}"
                )

            bad_rows = _rows(
                self._execute(
                    connection,
                    f"""
                    SELECT COUNT(*) AS invalid_provenance_count
                    FROM {self.table_name}
                    WHERE source_metadata->'migration'->>'source' = 'manifest.csv'
                      AND COALESCE(
                          source_metadata->'migration'->>'source_row' ~ '^[1-9][0-9]*$',
                          FALSE
                      ) = FALSE
                    """,
                )
            )
            bad_value = _first_value(bad_rows[0], "invalid_provenance_count") if bad_rows else None
            if bad_value is None or int(bad_value) != 0:
                raise RuntimeError(f"manifest provenance 형식 불일치 행이 있습니다: {bad_value}")

            index_rows = _rows(
                self._execute(
                    connection,
                    """
                    SELECT i.indisunique, i.indisvalid, i.indisready
                    FROM pg_index AS i
                    JOIN pg_class AS c ON c.oid = i.indexrelid
                    JOIN pg_namespace AS n ON n.oid = c.relnamespace
                    WHERE n.nspname = current_schema()
                      AND c.relname = 'uq_rs_disclosure_documents_manifest_source_row'
                    """,
                )
            )
            if not index_rows:
                raise RuntimeError("manifest source_row unique index가 없습니다")
            index_row = index_rows[0]
            index_values = index_row if isinstance(index_row, Mapping) else {}
            if isinstance(index_row, (tuple, list)):
                index_values = {
                    "indisunique": index_row[0] if len(index_row) > 0 else None,
                    "indisvalid": index_row[1] if len(index_row) > 1 else None,
                    "indisready": index_row[2] if len(index_row) > 2 else None,
                }
            if not all(bool(index_values.get(name)) for name in ("indisunique", "indisvalid", "indisready")):
                raise RuntimeError(f"manifest source_row unique index가 유효하지 않습니다: {index_values}")

            metadata_rows = _rows(
                self._execute(
                    connection,
                    f"""
                    SELECT COUNT(*) AS forbidden_metadata_count
                    FROM {self.table_name}
                    WHERE source_metadata ?| ARRAY[
                        'document_key', 'product_version_key', 'identity_version'
                    ]
                    """,
                )
            )
            metadata_value = _first_value(metadata_rows[0], "forbidden_metadata_count") if metadata_rows else None
            if metadata_value is None or int(metadata_value) != 0:
                raise RuntimeError(
                    "source_metadata에 authoritative identity 중복 필드가 남아 있습니다: "
                    f"{metadata_value}"
                )
            result.checks["manifest_provenance_contract"] = True
            result.checks["source_metadata_contract"] = True
        except Exception as exc:
            result.checks["manifest_provenance_contract"] = False
            result.checks["source_metadata_contract"] = False
            result.errors.append(f"manifest provenance/source metadata contract: {type(exc).__name__}: {exc}")

        try:
            rows = _rows(
                self._execute(
                    connection,
                    """
                    SELECT has_table_privilege(current_user, %s, 'SELECT') AS can_select,
                           has_table_privilege(current_user, %s, 'INSERT') AS can_insert,
                           has_table_privilege(current_user, %s, 'UPDATE') AS can_update
                    """,
                    (self.table_name, self.table_name, self.table_name),
                )
            )
            row = rows[0] if rows else None
            values = row if isinstance(row, Mapping) else {}
            if not all(bool(values.get(name)) for name in ("can_select", "can_insert", "can_update")):
                raise RuntimeError(f"DB 권한 부족: {dict(values)}")
            result.checks["permissions"] = True
        except Exception as exc:
            result.checks["permissions"] = False
            result.errors.append(f"DB 권한: {type(exc).__name__}: {exc}")

        result.checks["outbox_rw"] = self._check_outbox(result)
        result.ready = not result.errors and all(result.checks.values())
        if owns_lock:
            self.release_migration_lock()

        return result

    def _acquire_migration_lock(self, connection: Any | None = None) -> bool:
        """shared lock을 한 번 획득하고 connection에 귀속한다."""

        if self.migration_lock_held:
            return True
        connection = connection or self.connection
        lock_row = _rows(
            self._execute(
                connection,
                "SELECT pg_try_advisory_lock_shared(%s) AS acquired",
                (self.advisory_lock_key,),
            )
        )
        acquired = bool(_first_value(lock_row[0], "acquired")) if lock_row else False
        if acquired:
            self._guard_connection = connection
        return acquired

    def _check_outbox(self, result: DBReadinessResult) -> bool:
        try:
            directories = {
                *self.outbox_dirs,
                *(path.parent for path in self.outbox_paths),
            }
            for directory in directories:
                directory.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=directory, prefix=".readiness-", delete=True):
                    pass
            for path in self.outbox_paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                # 기존 JSONL/ACK/failure/quarantine를 읽어 손상을 조기에
                # 검출한다. 파일이 없어도 정상(아직 보류 이벤트가 없음)이다.
                DatabaseOutbox(path).pending()
                for companion in (
                    path.with_suffix(path.suffix + ".acked"),
                    path.with_suffix(path.suffix + ".failures"),
                    path.with_suffix(path.suffix + ".quarantined"),
                    path.with_suffix(path.suffix + ".quarantine.jsonl"),
                    path.with_suffix(path.suffix + ".compactions.jsonl"),
                ):
                    if companion.exists():
                        with companion.open("r", encoding="utf-8") as stream:
                            for line_number, line in enumerate(stream, start=1):
                                if not line.strip():
                                    continue
                                if companion.suffix in {".acked", ".quarantined"}:
                                    if not line.strip():
                                        raise RuntimeError(f"빈 ACK/quarantine event: {companion}:{line_number}")
                                else:
                                    parsed = json.loads(line)
                                    if not isinstance(parsed, dict):
                                        raise RuntimeError(f"outbox audit JSON 객체가 아닙니다: {companion}:{line_number}")
            return True
        except Exception as exc:
            result.errors.append(f"DB outbox read/write: {type(exc).__name__}: {exc}")
            return False

    def ensure(self, *, hold_migration_lock: bool = False) -> DBReadinessResult:
        if hold_migration_lock:
            # 검사 시작 전에 lock을 잡아 preflight와 실제 수집 사이의
            # migration 경쟁 창을 없애고, run() 종료까지 같은 session에서
            # 유지한다. 실패 시에도 즉시 해제한다.
            try:
                connection = self.connection
                if not self._acquire_migration_lock(connection):
                    raise DBReadinessError(
                        DBReadinessResult(
                            ready=False,
                            checks={"migration_advisory_lock": False},
                            errors=["migration advisory lock이 사용 중입니다"],
                        )
                    )
                result = self.check()
            except Exception:
                if self.migration_lock_held:
                    self.release_migration_lock()
                raise
            if not result.ready:
                self.release_migration_lock()
                raise DBReadinessError(result)
            return result

        result = self.check()
        if not result.ready:
            raise DBReadinessError(result)
        return result

    def release_migration_lock(self) -> None:
        if self._guard_connection is None:
            return
        try:
            self._execute(
                self._guard_connection,
                "SELECT pg_advisory_unlock_shared(%s)",
                (self.advisory_lock_key,),
            )
        finally:
            self._guard_connection = None
