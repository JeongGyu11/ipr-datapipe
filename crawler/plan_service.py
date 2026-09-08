"""장기 기간 백필용 문서 다운로드 계획.

상품 목록/상세 수집과 파일 다운로드를 분리하기 위한 작은 영속 계층이다.
계획 본문은 append-only JSONL 로 유지하고, 실행 상태는 별도 state JSONL 에
기록한다. 따라서 수천 개 상품을 조회하는 실행이 중단되어도 이미 수집한
계획을 보존한 채 다운로드만 재개할 수 있다.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable, Iterator, Mapping, TypeVar

from models.document import Document
from models.product_version import ProductVersion
from utils.crawler_logger import get_logger
from utils.network_io import (
    durable_append_bytes,
    durable_write_bytes,
    retry_file_operation,
    safe_fsync,
    safe_unlink,
    strict_exists,
)


PLAN_SCHEMA_VERSION = 3
PLAN_FILENAME = "download_plan.v3.jsonl"
PLAN_STATE_FILENAME = "download_state.v3.jsonl"
PLAN_MONTHS_DIRNAME = "months.v3"
_JsonlValue = TypeVar("_JsonlValue")


def _date_text(value: date | str | None) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "")


def _date_value(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _jsonable(value):
    """Adapter 부가정보를 JSON으로 저장할 수 있는 값으로 제한한다."""
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except (TypeError, ValueError):
        return str(value)


@dataclass
class PlanItem:
    """다운로드에 필요한 상품 버전 + 문서 메타데이터 한 건."""

    company_code: str = ""
    company_name: str = ""
    storage_name: str = ""
    product_category: str = ""
    product_name_raw: str = ""
    source_product_id: str = ""
    sale_status: str = ""
    sale_start_date: str = ""
    sale_end_date: str = ""
    disclosure_date: str = ""
    revision_date: str = ""
    target_date: str = ""
    date_basis: str = ""
    version_key: str = ""
    source_page_url: str = ""
    document_type: str = ""
    document_label: str = ""
    document_url: str = ""
    original_filename: str = ""
    download_hint: dict = field(default_factory=dict)
    version_extra: dict = field(default_factory=dict)
    month: str = ""
    schema_version: int = PLAN_SCHEMA_VERSION
    planned_at: str = ""

    def dedupe_key(self) -> str:
        """현재 schema에 맞는 영속 plan key 원문을 반환한다."""
        return self.identity_key()

    def identity_key(self) -> str:
        """판매 상태/종료일과 무관한 논리 문서 식별자."""
        if not str(self.storage_name or "").strip():
            raise ValueError("plan storage_name이 비어 있습니다")
        hint = json.dumps(self.download_hint or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "|".join(
            (
                self.company_code,
                self.storage_name,
                self.source_product_id,
                self.product_name_raw,
                self.target_date,
                self.sale_start_date,
                self.version_key,
                self.document_type,
                self.document_url or self.original_filename,
                hint,
            )
        )

    @property
    def key(self) -> str:
        return self.dedupe_key()

    @property
    def plan_key(self) -> str:
        return hashlib.sha256(self.dedupe_key().encode("utf-8")).hexdigest()

    def month_key(self) -> str:
        if self.month:
            return self.month
        return self.target_date[:7] if len(self.target_date) >= 7 else "UNKNOWN"

    def to_row(self) -> dict:
        if not str(self.storage_name or "").strip():
            raise ValueError("plan storage_name이 비어 있습니다")
        row = asdict(self)
        row["plan_key"] = self.plan_key
        return row

    @classmethod
    def from_row(cls, row: Mapping) -> "PlanItem":
        if not isinstance(row, Mapping):
            raise ValueError("plan row must be an object")
        version = row.get("schema_version")
        try:
            supported = int(version) == PLAN_SCHEMA_VERSION
        except (TypeError, ValueError):
            supported = False
        if not supported:
            raise ValueError(f"지원하지 않는 plan schema_version: {version!r}")
        if not str(row.get("storage_name") or "").strip():
            raise ValueError("plan storage_name이 비어 있습니다")
        values = {name: row.get(name, "") for name in cls.__dataclass_fields__}
        values["schema_version"] = PLAN_SCHEMA_VERSION
        hint = values.get("download_hint")
        if not isinstance(hint, dict):
            values["download_hint"] = {}
        extra = values.get("version_extra")
        if not isinstance(extra, dict):
            values["version_extra"] = {}
        if not values.get("month") and values.get("target_date"):
            values["month"] = str(values["target_date"])[:7]
        return cls(**values)

    @classmethod
    def from_version(cls, version: ProductVersion, document: Document) -> "PlanItem":
        target = version.target_date
        if not str(version.storage_name or "").strip():
            raise ValueError("ProductVersion.storage_name이 비어 있습니다")
        return cls(
            company_code=version.company_code,
            company_name=version.company_name,
            storage_name=version.storage_name,
            product_category=version.product_category,
            product_name_raw=version.product_name_raw,
            source_product_id=version.source_product_id,
            sale_status=version.sale_status,
            sale_start_date=_date_text(version.sale_start_date),
            sale_end_date=_date_text(version.sale_end_date),
            disclosure_date=_date_text(version.disclosure_date),
            revision_date=_date_text(version.revision_date),
            target_date=_date_text(target),
            date_basis=version.date_basis,
            version_key=version.version_key,
            source_page_url=version.source_page_url,
            document_type=document.document_type,
            document_label=document.document_label,
            document_url=document.document_url,
            original_filename=document.original_filename,
            download_hint=_jsonable(document.download_hint or {}),
            version_extra=_jsonable(version.extra or {}),
            month=target.strftime("%Y-%m") if target else "UNKNOWN",
            planned_at=datetime.now().isoformat(timespec="seconds"),
        )

    def to_version(self) -> ProductVersion:
        return ProductVersion(
            company_code=self.company_code,
            company_name=self.company_name,
            storage_name=self.storage_name,
            product_name_raw=self.product_name_raw,
            source_page_url=self.source_page_url,
            product_category=self.product_category,
            source_product_id=self.source_product_id,
            version_key=self.version_key,
            sale_status=self.sale_status,
            sale_start_date=_date_value(self.sale_start_date),
            sale_end_date=_date_value(self.sale_end_date),
            disclosure_date=_date_value(self.disclosure_date),
            revision_date=_date_value(self.revision_date),
            extra=dict(self.version_extra or {}),
        )

    def to_document(self) -> Document:
        return Document(
            document_type=self.document_type,
            document_label=self.document_label,
            document_url=self.document_url,
            original_filename=self.original_filename,
            download_hint=dict(self.download_hint or {}),
        )


class PlanService:
    """Append-only plan writer/reader and monthly index builder."""

    def __init__(
        self,
        plan_path: str | Path,
        state_path: str | Path | None = None,
        *,
        repair: bool = True,
    ):
        self.plan_path = Path(plan_path)
        if state_path is not None:
            self.state_path = Path(state_path)
        elif self.plan_path.name == PLAN_FILENAME:
            self.state_path = self.plan_path.with_name(PLAN_STATE_FILENAME)
        else:
            self.state_path = self.plan_path.with_name(f"{self.plan_path.stem}.state.v3.jsonl")
        self._plan_newline = b"\n"
        self._state_newline = b"\n"
        self._repair = repair
        self._keys: set[str] = set()
        self._items_by_key: dict[str, PlanItem] = {}
        self._items_by_identity: dict[str, PlanItem] = {}
        self._states: dict[str, dict] = {}
        self._scan_existing()

    def _scan_existing(self) -> None:
        if retry_file_operation(
            lambda: strict_exists(self.plan_path),
            path=self.plan_path,
            operation_name="plan 파일 존재 확인",
        ):
            for item in self.iter_items():
                dedupe_key = item.dedupe_key()
                identity_key = item.identity_key()
                self._keys.add(identity_key)
                self._items_by_key[dedupe_key] = item
                self._items_by_identity[identity_key] = item
        if retry_file_operation(
            lambda: strict_exists(self.state_path),
            path=self.state_path,
            operation_name="state 파일 존재 확인",
        ):
            items_by_plan_key = {item.plan_key: item for item in self._items_by_key.values()}

            def parse_state(row):
                if not isinstance(row, Mapping):
                    raise ValueError("state row must be an object")
                try:
                    if int(row.get("schema_version")) != PLAN_SCHEMA_VERSION:
                        raise ValueError("지원하지 않는 plan 상태 schema_version")
                except (TypeError, ValueError) as exc:
                    raise ValueError("지원하지 않는 plan 상태 schema_version") from exc
                plan_value = row.get("plan_key")
                dedupe_value = row.get("dedupe_key")
                if plan_value is not None and not isinstance(plan_value, str):
                    raise ValueError("state row plan_key must be a string")
                if dedupe_value is not None and not isinstance(dedupe_value, str):
                    raise ValueError("state row dedupe_key must be a string")
                plan_key = plan_value.strip() if isinstance(plan_value, str) else ""
                dedupe_key = dedupe_value if isinstance(dedupe_value, str) else ""
                if not plan_key and not dedupe_key:
                    raise ValueError("state row key is missing")
                item = self._items_by_key.get(dedupe_key) if dedupe_key else None
                if dedupe_key and item is None:
                    raise ValueError("state row dedupe_key is orphaned")
                if plan_key and dedupe_key:
                    expected = hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()
                    if plan_key != expected or item is None or item.plan_key != plan_key:
                        raise ValueError("state row plan_key does not match dedupe_key")
                elif dedupe_key:
                    plan_key = item.plan_key
                elif plan_key not in items_by_plan_key:
                    raise ValueError("state row plan_key is orphaned")
                normalized = dict(row)
                normalized["plan_key"] = plan_key
                if dedupe_key:
                    normalized["dedupe_key"] = dedupe_key
                return plan_key, normalized

            for key, row in self._iter_jsonl(self.state_path, parse_state, "plan 상태"):
                self._states[key] = row

    def iter_items(self) -> Iterator[PlanItem]:
        if not retry_file_operation(
            lambda: strict_exists(self.plan_path),
            path=self.plan_path,
            operation_name="plan 파일 존재 확인",
        ):
            return
        seen: set[str] = set()
        for item in self._iter_jsonl(self.plan_path, PlanItem.from_row, "plan"):
            key = item.identity_key()
            if key in seen:
                continue
            seen.add(key)
            yield item

    @staticmethod
    def _truncate_torn_tail(path: Path, byte_offset: int) -> None:
        """마지막 비정상 행을 제거하고 다음 append 경계를 내구화한다."""
        try:
            def truncate() -> None:
                with path.open("r+b") as fp:
                    fp.truncate(byte_offset)
                    fp.flush()
                    safe_fsync(fp, path=path)
            retry_file_operation(truncate, path=path, operation_name="plan torn tail 복구")
        except OSError as exc:
            raise RuntimeError(f"손상된 {path.name} 파일을 복구할 수 없습니다: {path}") from exc

    @staticmethod
    def _preferred_newline(raw_bytes: bytes) -> bytes:
        crlf_count = raw_bytes.count(b"\r\n")
        lf_count = raw_bytes.count(b"\n")
        return b"\r\n" if crlf_count and crlf_count == lf_count else b"\n"

    def _append_terminal_newline(self, path: Path, newline: bytes) -> None:
        """정상 JSON 행의 누락된 종료 개행을 append 경계에 복구한다."""
        try:
            durable_append_bytes(path, newline)
        except OSError as exc:
            raise RuntimeError(f"{path.name} 파일의 종료 개행을 복구할 수 없습니다: {path}") from exc

    def _iter_jsonl(
        self,
        path: Path,
        parser: Callable[[object], _JsonlValue],
        label: str,
    ) -> Iterator[_JsonlValue]:
        """JSONL을 엄격히 읽되, newline 없는 마지막 torn 행만 복구한다."""
        try:
            raw_bytes = retry_file_operation(
                path.read_bytes,
                path=path,
                operation_name=f"{label} 파일 읽기",
            )
        except OSError as exc:
            raise RuntimeError(f"{label} 파일을 읽을 수 없습니다: {path}: {exc}") from exc
        newline = self._preferred_newline(raw_bytes)
        if path == self.plan_path:
            self._plan_newline = newline
        elif path == self.state_path:
            self._state_newline = newline

        lines: list[bytes] = []
        line_starts: list[int] = []
        start = 0
        index = 0
        while index < len(raw_bytes):
            if raw_bytes[index] == 0x0A:
                end = index + 1
            elif raw_bytes[index] == 0x0D:
                end = index + 2 if index + 1 < len(raw_bytes) and raw_bytes[index + 1] == 0x0A else index + 1
            else:
                index += 1
                continue
            line_starts.append(start)
            lines.append(raw_bytes[start:end])
            start = end
            index = end
        if start < len(raw_bytes):
            line_starts.append(start)
            lines.append(raw_bytes[start:])

        nonempty = [index for index, line in enumerate(lines) if line.strip()]
        last_nonempty = nonempty[-1] if nonempty else -1

        for index, line in enumerate(lines):
            if not line.strip():
                continue
            has_terminator = line.endswith((b"\n", b"\r"))
            try:
                value = parser(json.loads(line.decode("utf-8")))
            except Exception as exc:  # malformed JSON and type/schema errors are corruption
                # A final row without a line terminator can be a process-killed write.
                # Newline-terminated corruption (including the last row) is fatal.
                if index == last_nonempty and not has_terminator:
                    if self._repair:
                        self._truncate_torn_tail(path, line_starts[index])
                    continue
                raise RuntimeError(f"{label} 중간 행이 손상되었습니다: {path}:{index + 1}") from exc
            if self._repair and index == last_nonempty and not has_terminator:
                newline = self._plan_newline if path == self.plan_path else self._state_newline
                self._append_terminal_newline(path, newline)
            yield value

    def items(self) -> list[PlanItem]:
        return list(self.iter_items())

    def add(self, item: PlanItem) -> PlanItem | None:
        """계획에 추가한다. 동일 고유키는 첫 항목을 유지한다."""
        identity_key = item.identity_key()
        if identity_key in self._keys:
            return None
        item.schema_version = PLAN_SCHEMA_VERSION
        if not item.planned_at:
            item.planned_at = datetime.now().isoformat(timespec="seconds")
        retry_file_operation(
            lambda: self.plan_path.parent.mkdir(parents=True, exist_ok=True),
            path=self.plan_path.parent,
            operation_name="plan 디렉터리 생성",
        )
        payload = json.dumps(item.to_row(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            durable_append_bytes(self.plan_path, payload + self._plan_newline)
        except OSError as exc:
            raise RuntimeError(f"plan 파일에 기록할 수 없습니다: {self.plan_path}") from exc
        self._keys.add(identity_key)
        self._items_by_key[item.dedupe_key()] = item
        self._items_by_identity[identity_key] = item
        return item

    def add_version(self, version: ProductVersion, document: Document) -> PlanItem | None:
        return self.add(PlanItem.from_version(version, document))

    def ensure_version(self, version: ProductVersion, document: Document) -> PlanItem:
        """계획 항목을 보장하고 신규/기존 항목 모두 반환한다."""
        candidate = PlanItem.from_version(version, document)
        key = candidate.identity_key()
        existing = self._items_by_identity.get(key)
        if existing is not None:
            return existing
        added = self.add(candidate)
        # 같은 프로세스의 경쟁 추가가 생겨도 최종 항목을 반환한다.
        return added or self._items_by_identity[key]

    def add_versions(
        self,
        versions: Iterable[ProductVersion],
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        include_manual_review: bool = False,
    ) -> int:
        count = 0
        for version in versions:
            target = version.target_date
            if target is None:
                if not include_manual_review:
                    continue
            elif start_date and target < start_date:
                continue
            elif end_date and target > end_date:
                continue
            for document in version.documents:
                if self.add_version(version, document) is not None:
                    count += 1
        return count

    def mark_result(self, item: PlanItem, result, *, error: str = "") -> None:
        """다운로드 결과를 append-only 상태 저널에 기록한다."""
        status = getattr(result, "download_status", result if isinstance(result, str) else "")
        row = {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_key": item.plan_key,
            "dedupe_key": item.dedupe_key(),
            "download_status": status,
            "saved_relative_path": getattr(result, "saved_relative_path", ""),
            "sha256": getattr(result, "sha256", ""),
            "error_message": error or getattr(result, "error_message", ""),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        retry_file_operation(
            lambda: self.state_path.parent.mkdir(parents=True, exist_ok=True),
            path=self.state_path.parent,
            operation_name="plan 상태 디렉터리 생성",
        )
        payload = json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            durable_append_bytes(self.state_path, payload + self._state_newline)
        except OSError as exc:
            raise RuntimeError(f"plan 상태 파일에 기록할 수 없습니다: {self.state_path}") from exc
        self._states[item.plan_key] = row

    def state(self, item: PlanItem) -> dict | None:
        return self._states.get(item.plan_key)

    def pending_items(self, *, verify_files: bool = True) -> Iterator[PlanItem]:
        """상태상 미완료인 plan 항목을 반환한다.

        기본값은 성공 상태의 ``saved_relative_path``를 실제로 확인해, 파일이
        유실된 항목을 다시 처리할 수 있도록 한다. 실행 종료 후 남은
        항목 수처럼 상태 저널만 필요한 호출부는 ``verify_files=False``를
        사용해 각 네트워크 경로의 중복 stat을 피할 수 있다.
        """
        from models.document import DownloadStatus

        for item in self.iter_items():
            state = self._states.get(item.plan_key)
            if state and state.get("download_status") in DownloadStatus.COMPLETED:
                if not verify_files:
                    continue
                saved_path = str(state.get("saved_relative_path") or "")
                # 성공 상태만 남고 실제 파일이 사라진 경우에는 다시 처리한다.
                resolved_saved = self._resolve_saved_relative_path(saved_path)
                if resolved_saved and retry_file_operation(
                    lambda: strict_exists(resolved_saved),
                    path=resolved_saved,
                    operation_name="plan 성공 파일 존재 확인",
                ):
                    continue
            yield item

    def _resolve_saved_relative_path(self, value: str) -> Path | None:
        """plan 위치에서 출력 루트를 찾아 저장 상대경로를 검증한다."""
        text = str(value or "").replace("\\", "/")
        if not text or text.startswith("/") or ":" in text.split("/", 1)[0]:
            return None
        operations = next((parent for parent in self.plan_path.parents if parent.name == "99_운영"), None)
        if operations is None:
            return None
        root = operations.parent.resolve()
        candidate = (root / text).resolve()
        if candidate != root and root not in candidate.parents:
            return None
        return candidate

    def pending_count(self, *, verify_files: bool = True) -> int:
        """현재 plan의 pending 항목 수를 센다.

        ``verify_files=False``이면 최신 state의 완료 상태만 사용한다.
        기본값은 :meth:`pending_items`와 동일하게 파일 유실을 검출한다.
        """
        return sum(1 for _ in self.pending_items(verify_files=verify_files))

    def create_monthly_index(self, index_dir: str | Path | None = None) -> dict[str, list[str]]:
        """월별 plan_key 인덱스와 월별 JSON 파일을 원자적으로 생성한다."""
        root = Path(index_dir) if index_dir else self.plan_path.parent / PLAN_MONTHS_DIRNAME
        retry_file_operation(
            lambda: root.mkdir(parents=True, exist_ok=True),
            path=root,
            operation_name="plan 월별 인덱스 디렉터리 생성",
        )
        grouped: dict[str, list[str]] = {}
        for item in self.iter_items():
            grouped.setdefault(item.month_key(), []).append(item.plan_key)
        for month, keys in grouped.items():
            self._atomic_json(root / f"{month}.json", keys)
        self._atomic_json(root / "monthly_index.json", grouped)
        return grouped

    def _atomic_json(self, path: Path, value) -> None:
        retry_file_operation(
            lambda: path.parent.mkdir(parents=True, exist_ok=True),
            path=path.parent,
            operation_name="plan 인덱스 디렉터리 생성",
        )
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            os.close(fd)
            durable_write_bytes(
                name,
                json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8"),
            )
            retry_file_operation(
                lambda: os.replace(name, path),
                path=path,
                operation_name="plan 인덱스 원자 교체",
            )
        finally:
            try:
                safe_unlink(name)
            except OSError:
                get_logger().warning("plan 인덱스 임시 파일 정리 실패: %s", name)


__all__ = [
    "PLAN_FILENAME",
    "PLAN_MONTHS_DIRNAME",
    "PLAN_SCHEMA_VERSION",
    "PLAN_STATE_FILENAME",
    "PlanItem",
    "PlanService",
]
