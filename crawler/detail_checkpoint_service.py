"""상품 상세 조회 결과를 재개하기 위한 공통 append-only 체크포인트.

체크포인트는 다운로드 manifest와 분리된 작은 JSONL 저널이다. 한 상품의
마지막 상태만 메모리에 유지하므로 ``failed`` 기록 뒤의 ``completed`` 기록이
항상 최신 상태가 된다. 강제 종료로 잘린 마지막 줄만 무시하며, 중간 줄의
손상은 안전을 위해 예외로 중단한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from models.document import Document
from models.product_version import ProductVersion
from utils.network_io import durable_append_bytes, retry_file_operation, safe_fsync, strict_exists


CHECKPOINT_VERSION = 2
KeyFn = Callable[[dict[str, Any]], str]


def _date_to_text(value: date | None) -> str | None:
    return value.isoformat() if isinstance(value, date) else None


def _text_to_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _document_to_dict(document: Document) -> dict[str, Any]:
    return {
        "document_type": document.document_type,
        "document_label": document.document_label,
        "document_url": document.document_url,
        "original_filename": document.original_filename,
        "download_hint": document.download_hint,
    }


def _document_from_dict(data: dict[str, Any]) -> Document:
    return Document(
        document_type=str(data.get("document_type", "")),
        document_label=str(data.get("document_label", "")),
        document_url=str(data.get("document_url", "")),
        original_filename=str(data.get("original_filename", "")),
        download_hint=dict(data.get("download_hint") or {}),
    )


def _version_to_dict(version: ProductVersion) -> dict[str, Any]:
    if not str(version.storage_name or "").strip():
        raise ValueError("checkpoint storage_name이 비어 있습니다")
    return {
        "company_code": version.company_code,
        "company_name": version.company_name,
        "storage_name": version.storage_name,
        "product_name_raw": version.product_name_raw,
        "product_category": version.product_category,
        "source_product_id": version.source_product_id,
        "version_key": version.version_key,
        "sale_status": version.sale_status,
        "sale_start_date": _date_to_text(version.sale_start_date),
        "sale_end_date": _date_to_text(version.sale_end_date),
        "disclosure_date": _date_to_text(version.disclosure_date),
        "revision_date": _date_to_text(version.revision_date),
        "source_page_url": version.source_page_url,
        "extra": version.extra,
        "documents": [_document_to_dict(document) for document in version.documents],
    }


def _version_from_dict(data: dict[str, Any]) -> ProductVersion:
    documents = data.get("documents") or []
    if not isinstance(documents, list) or any(not isinstance(item, dict) for item in documents):
        raise ValueError("invalid checkpoint documents")
    if not str(data.get("storage_name") or "").strip():
        raise ValueError("checkpoint storage_name이 비어 있습니다")
    return ProductVersion(
        company_code=str(data.get("company_code", "")),
        company_name=str(data.get("company_name", "")),
        storage_name=str(data.get("storage_name", "")),
        product_name_raw=str(data.get("product_name_raw", "")),
        product_category=str(data.get("product_category", "")),
        source_product_id=str(data.get("source_product_id", "")),
        version_key=str(data.get("version_key", "")),
        sale_status=str(data.get("sale_status", "")),
        sale_start_date=_text_to_date(data.get("sale_start_date")),
        sale_end_date=_text_to_date(data.get("sale_end_date")),
        disclosure_date=_text_to_date(data.get("disclosure_date")),
        revision_date=_text_to_date(data.get("revision_date")),
        source_page_url=str(data.get("source_page_url", "")),
        extra=dict(data.get("extra") or {}),
        documents=[_document_from_dict(item) for item in documents],
    )


@dataclass
class DetailCheckpoint:
    """상품 하나의 마지막 상세 조회 결과."""

    key: str
    product: dict[str, Any] = field(default_factory=dict)
    status: str = "failed"
    versions: list[ProductVersion] = field(default_factory=list)
    error: str = ""
    fetched_at: str = ""
    scope: str = ""
    schema_version: int = CHECKPOINT_VERSION
    adapter_version: str = ""

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "key": self.key,
            "product": self.product,
            "status": self.status,
            "versions": [_version_to_dict(version) for version in self.versions],
            "error": self.error,
            "fetched_at": self.fetched_at,
        }
        if self.scope:
            result["scope"] = self.scope
        if self.adapter_version:
            result["adapter_version"] = self.adapter_version
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DetailCheckpoint":
        if not isinstance(data, dict):
            raise ValueError("checkpoint row must be an object")
        raw_key = data.get("key", "")
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ValueError("invalid checkpoint key")
        product = data.get("product")
        versions = data.get("versions")
        if not isinstance(product, dict) or not isinstance(versions, list):
            raise ValueError("invalid checkpoint product or versions")
        if any(not isinstance(item, dict) for item in versions):
            raise ValueError("invalid checkpoint version")
        schema_value = data.get("schema_version")
        try:
            if int(schema_value) != CHECKPOINT_VERSION:
                raise ValueError(f"지원하지 않는 checkpoint schema_version: {schema_value!r}")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"지원하지 않는 checkpoint schema_version: {schema_value!r}") from exc
        return cls(
            key=raw_key.strip(),
            product=dict(product),
            status=str(data.get("status", "failed")),
            versions=[_version_from_dict(item) for item in versions],
            error=str(data.get("error", "")),
            fetched_at=str(data.get("fetched_at", "")),
            scope=str(data.get("scope", "")),
            schema_version=CHECKPOINT_VERSION,
            adapter_version=str(data.get("adapter_version", "")),
        )


class DetailCheckpointService:
    """상세 결과 JSONL 저장소.

    ``root``가 JSONL 파일이면 그대로 사용하고, 디렉터리이면
    ``root/scope/filename``을 사용한다. ``path=``는 두 형태보다 우선한다.
    구버전 저널은 자동 변환하거나 fallback하지 않는다. 운영자는 새 v2
    파일명으로 재수집을 시작해야 한다.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        scope: str = "default",
        *,
        path: str | Path | None = None,
        filename: str = "detail_checkpoint.v2.jsonl",
        key_fn: KeyFn | None = None,
        adapter_version: str = "",
        schema_version: int = CHECKPOINT_VERSION,
    ):
        if path is not None:
            self.path = Path(path)
        elif root is not None:
            root_path = Path(root)
            self.path = root_path if root_path.suffix.lower() in {".jsonl", ".json"} else root_path / scope / filename
        else:
            raise ValueError("root 또는 path가 필요합니다")
        self.scope = str(scope)
        self.filename = filename
        self.key_fn = key_fn or self._default_key
        self.adapter_version = str(adapter_version)
        self.schema_version = int(schema_version)
        if self.schema_version != CHECKPOINT_VERSION:
            raise ValueError(f"지원하지 않는 checkpoint schema_version: {self.schema_version}")
        self._newline = b"\n"
        retry_file_operation(
            lambda: self.path.parent.mkdir(parents=True, exist_ok=True),
            path=self.path.parent,
            operation_name="detail checkpoint 디렉터리 생성",
        )
        self.records: dict[str, DetailCheckpoint] = {}
        self._load()

    @staticmethod
    def _default_key(product: dict[str, Any]) -> str:
        for name in ("product_id", "product_code", "id", "source_product_id"):
            value = product.get(name)
            if value not in (None, ""):
                return str(value).strip()
        return "|".join(str(value).strip() for value in product.values())

    def _load(self) -> None:
        if not retry_file_operation(
            lambda: strict_exists(self.path),
            path=self.path,
            operation_name="detail checkpoint 파일 존재 확인",
        ):
            return
        try:
            raw_bytes = retry_file_operation(
                self.path.read_bytes,
                path=self.path,
                operation_name="detail checkpoint 읽기",
            )
            self._newline = self._preferred_newline(raw_bytes)
        except OSError as exc:
            raise RuntimeError(f"상세 체크포인트를 읽을 수 없습니다: {self.path}") from exc

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
                data = json.loads(line.decode("utf-8"))
                checkpoint = DetailCheckpoint.from_dict(data)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                if index == last_nonempty and not has_terminator:
                    # 강제 종료로 쓰다 만 마지막 행은 버리고, 다음 append가
                    # 정상 JSONL 경계에서 시작하도록 즉시 truncate한다.
                    self._truncate_torn_tail(line_starts[index])
                    continue
                raise RuntimeError(f"상세 체크포인트 중간 행이 손상되었습니다: {self.path}:{index + 1}") from exc
            if not checkpoint.key:
                if index == last_nonempty and not has_terminator:
                    self._truncate_torn_tail(line_starts[index])
                    continue
                raise RuntimeError(f"상세 체크포인트 키가 없습니다: {self.path}:{index + 1}")
            if index == last_nonempty and not has_terminator:
                # A complete JSON value written without its final newline is
                # valid, but must be repaired before the next append so two
                # records cannot be concatenated into one invalid JSON value.
                self._append_terminal_newline(self._newline)
            # 현재 schema 안에서도 다른 scope/adapter 결과는 섞지 않는다.
            if checkpoint.scope and checkpoint.scope != self.scope:
                continue
            if not checkpoint.scope:
                continue
            if checkpoint.schema_version != self.schema_version:
                continue
            if self.adapter_version and checkpoint.adapter_version != self.adapter_version:
                continue
            self.records[checkpoint.key] = checkpoint

    def _truncate_torn_tail(self, byte_offset: int) -> None:
        """마지막 torn 행을 제거하고 파일 경계를 디스크에 내구화한다."""
        try:
            def _truncate() -> None:
                with self.path.open("r+b") as fp:
                    fp.truncate(byte_offset)
                    fp.flush()
                    safe_fsync(fp, path=self.path)
            retry_file_operation(_truncate, path=self.path, operation_name="상세 체크포인트 torn tail 복구")
        except OSError as exc:
            raise RuntimeError(f"손상된 상세 체크포인트를 복구할 수 없습니다: {self.path}") from exc

    @staticmethod
    def _preferred_newline(raw_bytes: bytes) -> bytes:
        crlf_count = raw_bytes.count(b"\r\n")
        lf_count = raw_bytes.count(b"\n")
        return b"\r\n" if crlf_count and crlf_count == lf_count else b"\n"

    def _append_terminal_newline(self, newline: bytes) -> None:
        """정상 마지막 행의 누락된 개행을 append 경계에 복구한다."""
        try:
            durable_append_bytes(self.path, newline)
        except OSError as exc:
            raise RuntimeError(f"상세 체크포인트 종료 개행을 복구할 수 없습니다: {self.path}") from exc

    def _key(self, key_or_product: str | dict[str, Any]) -> str:
        raw_key = key_or_product if isinstance(key_or_product, str) else self.key_fn(key_or_product)
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ValueError("checkpoint key is missing")
        return raw_key.strip()

    def get(self, key_or_product: str | dict[str, Any]) -> DetailCheckpoint | None:
        return self.records.get(self._key(key_or_product))

    def reusable(self, key_or_product: str | dict[str, Any]) -> DetailCheckpoint | None:
        checkpoint = self.get(key_or_product)
        return checkpoint if checkpoint and checkpoint.completed else None

    def record_success(self, product: dict[str, Any], versions: Iterable[ProductVersion]) -> DetailCheckpoint:
        return self._record(DetailCheckpoint(
            key=self._key(product), product=dict(product), status="completed", versions=list(versions),
            fetched_at=datetime.now().isoformat(timespec="seconds"), scope=self.scope,
            schema_version=self.schema_version, adapter_version=self.adapter_version,
        ))

    def record_failure(self, product: dict[str, Any], error: str) -> DetailCheckpoint:
        return self._record(DetailCheckpoint(
            key=self._key(product), product=dict(product), status="failed", error=str(error),
            fetched_at=datetime.now().isoformat(timespec="seconds"), scope=self.scope,
            schema_version=self.schema_version, adapter_version=self.adapter_version,
        ))

    def _record(self, checkpoint: DetailCheckpoint) -> DetailCheckpoint:
        if not isinstance(checkpoint.key, str) or not checkpoint.key.strip():
            raise ValueError("checkpoint key is missing")
        checkpoint.key = checkpoint.key.strip()
        payload = json.dumps(checkpoint.to_dict(), ensure_ascii=False, separators=(",", ":"))
        try:
            durable_append_bytes(self.path, payload.encode("utf-8") + self._newline)
        except OSError as exc:
            raise RuntimeError(f"상세 체크포인트를 기록할 수 없습니다: {self.path}") from exc
        self.records[checkpoint.key] = checkpoint
        return checkpoint

    def completed_count(self) -> int:
        return sum(1 for checkpoint in self.records.values() if checkpoint.completed)
