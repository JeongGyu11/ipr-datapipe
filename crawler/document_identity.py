"""문서 식별자 생성.

마이그레이션과 실시간 수집이 동일한 규칙을 사용하도록 식별자 계산을 한
곳에 둔다. 신규 runtime identity는 canonical 입력을 BLAKE2b로 지문화한
뒤 종류별 접두사와 Base62 10자리 본문으로 표현한다. 파일 내용의 SHA-256(``sha256`` 컬럼)과
기존 archive/migration용 64자리 SHA-256 identity는 별도 계약으로 보존한다.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from models.document import Document
from models.product_version import ProductVersion

# Prefixes are part of the persisted identity contract.  The Base62 body is
# deliberately kept at ten characters so the 2026-08 short-key migration can
# preserve every existing body and only add an unambiguous type prefix.
IDENTITY_VERSION = 4
PRODUCT_VERSION_IDENTITY_VERSION = 2
SHORT_KEY_LENGTH = 10
DOCUMENT_KEY_PREFIX = "DOC_"
PRODUCT_VERSION_KEY_PREFIX = "PROD_VER_"
BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE62_SPACE = len(BASE62_ALPHABET) ** SHORT_KEY_LENGTH
_ROW_FIELDS = (
    "company_code", "source_product_id", "product_name_raw", "product_name",
    "product_name_normalized", "target_date", "document_date", "sale_start_date",
    "sale_end_date", "source_page_url", "document_type", "document_url",
    "original_filename", "source_locator", "checkpoint_key", "source_metadata",
)
_WHITESPACE = re.compile(r"\s+")
_SENSITIVE_KEY = re.compile(
    r"(?:cookie|token|encvalue|session|password|passwd|secret|credential|authorization|auth|"
    r"api[_-]?key|access[_-]?key|signature|sig|signed)",
    re.I,
)


def normalize_text(value: Any) -> str:
    """키에 사용할 문자열을 안정적으로 정규화한다."""
    if value is None:
        return ""
    return _WHITESPACE.sub(" ", str(value)).strip()


def _row_values(row: Any) -> dict[str, Any]:
    """dict, dataclass, class-attribute DTO를 동일한 row view로 읽는다."""
    if isinstance(row, dict):
        return dict(row)
    return {name: getattr(row, name, "") for name in _ROW_FIELDS}


def _date_text(value: date | datetime | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return normalize_text(value)


def _base62(value: int) -> str:
    """0 <= value < 62**10 정수를 고정 길이 Base62로 표현한다."""
    if not 0 <= value < BASE62_SPACE:
        raise ValueError("Base62 10자리 범위를 벗어난 값입니다")
    chars: list[str] = []
    for _ in range(SHORT_KEY_LENGTH):
        value, remainder = divmod(value, len(BASE62_ALPHABET))
        chars.append(BASE62_ALPHABET[remainder])
    return "".join(reversed(chars))


def _canonical_fingerprint(payload: Any, *, kind: str) -> str:
    """canonical JSON을 BLAKE2b로 지문화해 결정적 10자리 key를 만든다."""
    canonical = json.dumps(
        {"kind": kind, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.blake2b(canonical, digest_size=32).digest()
    # 62**10 namespace에 deterministic하게 사상한다. DB UNIQUE 제약과
    # migration 사전 충돌검사가 실제 uniqueness를 보장한다.
    return _base62(int.from_bytes(digest, "big") % BASE62_SPACE)


def _key_with_prefix(body: str, prefix: str) -> str:
    if len(body) != SHORT_KEY_LENGTH or any(char not in BASE62_ALPHABET for char in body):
        raise ValueError("Base62 10자리 key 본문이 아닙니다")
    return prefix + body


def _prefixed_key_body(value: Any, prefix: str) -> str:
    """Return the Base62 body from a current, type-prefixed key.

    Runtime identity v4 is deliberately strict: an unprefixed ten-character
    value is not a valid key and must not be accepted as a migration bridge.
    """
    text = normalize_text(value)
    if not text.startswith(prefix):
        raise ValueError(f"{prefix} key는 접두사가 필요합니다")
    body = text[len(prefix):]
    if len(body) != SHORT_KEY_LENGTH or any(char not in BASE62_ALPHABET for char in body):
        raise ValueError(f"{prefix} key 본문이 올바르지 않습니다")
    return body


def product_version_key_body(value: Any) -> str:
    return _prefixed_key_body(value, PRODUCT_VERSION_KEY_PREFIX)


def _safe_url_locator(value: Any) -> str:
    """URL을 원본 locator로 보존하되 query의 인증성분은 제거한다."""
    text = normalize_text(value)
    if not text:
        return ""
    # 이 형식은 아래의 재귀 sanitizing을 거쳐 생성한 opaque locator다.
    # 내부 JSON에 ``?``가 있더라도 URL parser로 다시 조립하면 identity가
    # 훼손되므로 URL로 취급하지 않는다.
    if text.startswith("POST|"):
        return text
    try:
        parts = urlsplit(text)
    except ValueError:
        return text
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    has_sensitive_query = any(_SENSITIVE_KEY.search(key) for key, _ in pairs)
    if not (parts.scheme and parts.netloc) and not has_sensitive_query:
        return text
    query = [
        (key, val) for key, val in pairs
        if not _SENSITIVE_KEY.search(key)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def source_locator_for_document(document: Any) -> str:
    """fetch 결과 URL과 무관한, 비밀값 없는 원본 문서 locator."""
    explicit = getattr(document, "source_locator", "") or ""
    if explicit:
        safe_explicit = _safe_url_locator(explicit)
        if safe_explicit:
            return safe_explicit
    url = getattr(document, "document_url", "") or ""
    if url:
        safe_url = _safe_url_locator(url)
        if safe_url:
            return safe_url
    hint = getattr(document, "download_hint", None)
    if isinstance(hint, dict) and hint:
        safe = _sanitize_metadata(hint)
        if isinstance(safe, dict):
            # POST body 전체가 아닌 안정적인 source fields만 identity에 사용한다.
            safe = {str(k): v for k, v in safe.items() if v not in (None, "", [], {})}
            if safe:
                return "POST|" + json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    filename = normalize_text(getattr(document, "original_filename", "") or "")
    if filename:
        return filename
    # query 자체가 전부 인증값이라 제거된 특수 상대 URL도 빈 locator로
    # 되돌려 원문 token을 identity에 다시 사용하지 않게 한다.
    if explicit or url:
        return "REDACTED_QUERY_LOCATOR"
    return ""


def manifest_identity_source(record: Any) -> str:
    """기존 ManifestRecord.key()와 호환되는 원문 식별자."""
    def get(name: str, default: Any = "") -> Any:
        if isinstance(record, dict):
            return record.get(name, default)
        return getattr(record, name, default)

    def legacy(value: Any) -> str:
        # ManifestRecord.key()는 trim/공백 정규화를 하지 않으므로 그대로 재현한다.
        return "" if value is None else str(value)

    checkpoint = legacy(get("checkpoint_key", ""))
    if checkpoint:
        return f"PLAN|{checkpoint}"
    # fetch/redirect 결과가 아닌 수집 시점의 원본 locator를 사용한다.
    # source_locator는 runtime record에 먼저 확정되어 PENDING과 terminal이
    # 동일한 identity를 공유한다.
    locator = legacy(get("source_locator", ""))
    if not locator:
        locator = legacy(get("document_url", ""))
    if not locator:
        locator = legacy(get("original_filename", ""))
    return "|".join(
        [
            legacy(get("company_code", "")),
            legacy(get("source_product_id", "")),
            legacy(get("product_name_raw", "")),
            legacy(get("target_date", "")),
            legacy(get("document_type", "")),
            locator,
        ]
    )


def _product_version_payload_from_row(row: Any) -> dict[str, Any]:
    values = _row_values(row)
    return {
        "identity_version": PRODUCT_VERSION_IDENTITY_VERSION,
        "company_code": normalize_text(values.get("company_code", "")),
        "source_product_id": normalize_text(values.get("source_product_id", "")),
        "product_name": normalize_text(values.get("product_name_raw", "")),
        "sale_start_date": normalize_text(values.get("sale_start_date", "")),
        "target_date": normalize_text(values.get("target_date", "")),
        "source_page_url": normalize_text(values.get("source_page_url", "")),
    }


def _runtime_product_version_key_from_row(row: Any) -> str:
    return _key_with_prefix(
        _canonical_fingerprint(
            _product_version_payload_from_row(row), kind="product_version"
        ),
        PRODUCT_VERSION_KEY_PREFIX,
    )


def document_key(record: Any, *, product_key: str | None = None) -> str:
    """상위 상품 버전과 안정 locator를 포함한 runtime 문서 key."""
    parent_key = product_key or _runtime_product_version_key_from_row(record)
    # Keep the pre-prefix product body in the hash payload.  Prefixes are a
    # presentation/type contract, not new identity entropy.
    parent_key = product_version_key_body(parent_key)
    payload = {
        "product_version_key": parent_key,
        "document_identity": manifest_identity_source(record),
    }
    return _key_with_prefix(_canonical_fingerprint(payload, kind="document"), DOCUMENT_KEY_PREFIX)


def product_version_payload(version: ProductVersion | Any) -> dict[str, Any]:
    """문서 종류·판매상태·저장경로에 영향을 받지 않는 버전 식별 정보."""
    source_product_id = normalize_text(getattr(version, "source_product_id", ""))
    product_name = normalize_text(getattr(version, "product_name_raw", ""))
    sale_start = _date_text(getattr(version, "sale_start_date", None))
    target_date = _date_text(getattr(version, "target_date", None))
    # manifest에 존재하는 값만 사용한다. version_key는 별도 metadata로 보존한다.
    return {
        "identity_version": PRODUCT_VERSION_IDENTITY_VERSION,
        "company_code": normalize_text(getattr(version, "company_code", "")),
        "source_product_id": source_product_id,
        "product_name": product_name,
        "sale_start_date": sale_start,
        "target_date": target_date,
        "source_page_url": normalize_text(getattr(version, "source_page_url", "")),
    }


def product_version_key(version: ProductVersion | Any) -> str:
    return _key_with_prefix(
        _canonical_fingerprint(product_version_payload(version), kind="product_version"),
        PRODUCT_VERSION_KEY_PREFIX,
    )


def product_version_key_for_context(version: ProductVersion | Any, record: Any | None = None) -> str:
    """runtime version이 일부 날짜를 채우지 못한 결과의 migration 호환 키."""
    payload = product_version_payload(version)
    if record is not None:
        def read(name: str) -> Any:
            if isinstance(record, dict):
                return record.get(name, "")
            return getattr(record, name, "")
        fallbacks = {
            "company_code": "company_code",
            "source_product_id": "source_product_id",
            "product_name": "product_name_raw",
            "sale_start_date": "sale_start_date",
            "target_date": "target_date",
            "source_page_url": "source_page_url",
        }
        for target, source in fallbacks.items():
            if not payload.get(target):
                payload[target] = normalize_text(read(source))
    return _key_with_prefix(
        _canonical_fingerprint(payload, kind="product_version"),
        PRODUCT_VERSION_KEY_PREFIX,
    )


def product_version_key_for_manifest(row: Any) -> str:
    """manifest CSV 행과 runtime ProductVersion이 공유하는 버전 키."""
    return _runtime_product_version_key_from_row(row)


def document_key_for_manifest(row: Any) -> str:
    """신규 runtime CSV/ManifestRecord용 결정적 BLAKE2b/Base62 key."""
    return document_key(row)


def document_key_for_database_row(row: Any) -> str:
    """DB-shaped row에서 신규 runtime document key를 계산한다.

    DB 컬럼명(``product_name``, ``document_date``)을 manifest identity
    입력명으로 투영하고, 저장된 parent key와 무관하게 신규 fields에서
    parent를 재계산한다.
    """
    values = _row_values(row)
    metadata = values.get("source_metadata") if isinstance(values.get("source_metadata"), dict) else {}
    projected = dict(values)
    if not projected.get("product_name_raw"):
        projected["product_name_raw"] = values.get("product_name", "")
    if not projected.get("target_date"):
        projected["target_date"] = values.get("document_date") or values.get("sale_start_date", "")
    if not projected.get("source_locator"):
        projected["source_locator"] = metadata.get("source_locator", "")
    # 저장된 64자리 legacy parent key는 새 identity 입력이 아니다.
    # 항상 projected fields에서 신규 parent를 다시 계산한다.
    parent_key = product_version_key_for_manifest(projected)
    return document_key(projected, product_key=parent_key)


def product_version_key_for_database_row(row: Any) -> str:
    """DB-shaped row에서 신규 runtime product version key를 계산한다."""
    values = _row_values(row)
    projected = dict(values)
    if not projected.get("product_name_raw"):
        projected["product_name_raw"] = values.get("product_name", "")
    if not projected.get("target_date"):
        projected["target_date"] = values.get("document_date") or values.get("sale_start_date", "")
    return product_version_key_for_manifest(projected)


@dataclass(frozen=True)
class DocumentIdentity:
    document_key: str
    product_version_key: str
    identity_version: int = IDENTITY_VERSION


def identity_for(version: ProductVersion | Any, document: Document, record: Any | None = None) -> DocumentIdentity:
    """상품 버전과 문서로 runtime identity를 계산한다."""
    if record is None:
        # Document URL/파일명과 ProductVersion의 기존 필드를 이용해
        # ManifestRecord와 동일한 composite를 구성한다.
        class _Record:
            pass

        record = _Record()
        record.company_code = getattr(version, "company_code", "")
        record.source_product_id = getattr(version, "source_product_id", "")
        record.product_name_raw = getattr(version, "product_name_raw", "")
        record.target_date = _date_text(getattr(version, "target_date", None))
        record.document_type = getattr(document, "document_type", "")
        record.document_url = getattr(document, "document_url", "")
        record.original_filename = getattr(document, "original_filename", "")
        record.source_locator = source_locator_for_document(document)
        record.checkpoint_key = ""
    elif not getattr(record, "source_locator", ""):
        # DownloadService가 만든 record에는 항상 fetch 전에 locator를 고정한다.
        # 외부 호출자가 직접 payload를 만들 때도 동일한 규칙을 보장한다.
        try:
            setattr(record, "source_locator", source_locator_for_document(document))
        except (AttributeError, TypeError):
            pass
    parent_key = product_version_key_for_context(version, record)
    return DocumentIdentity(document_key(record, product_key=parent_key), parent_key)


def metadata_for(version: ProductVersion | Any, document: Document | Any, record: Any | None = None) -> dict[str, Any]:
    """DB source_metadata에 저장할 비밀값 없는 부가정보."""
    # identity_version/document_key/product_version_key는 이미 DB의 최상위
    # 컬럼으로 저장된다. JSONB에 다시 넣으면 runtime 이벤트가 migration
    # provenance를 덮어쓸 때 어떤 값이 authoritative한지 모호해지므로
    # source_metadata에는 identity 부가정보를 중복 저장하지 않는다.
    metadata: dict[str, Any] = {}
    version_key = normalize_text(getattr(version, "version_key", ""))
    # checkpoint_key는 legacy ManifestRecord.key()의 identity 원문이다.
    # 앞뒤 공백까지 hash에 포함되므로 DB round-trip에서도 그대로 보존한다.
    checkpoint_value = getattr(record, "checkpoint_key", "") if record else ""
    checkpoint = "" if checkpoint_value is None else str(checkpoint_value)
    if version_key:
        metadata["source_version_key"] = version_key
    if checkpoint:
        metadata["checkpoint_key"] = checkpoint
    if isinstance(record, dict):
        locator = str(record.get("source_locator", "") or "")
    else:
        locator = str(getattr(record, "source_locator", "") or "") if record else ""
    locator = locator or source_locator_for_document(document)
    if locator:
        metadata["source_locator"] = locator
    final_value = record.get("final_url", "") if isinstance(record, dict) else getattr(record, "final_url", "")
    final_url = _safe_url_locator(final_value if record else "")
    if final_url and final_url != locator:
        metadata["final_url"] = final_url
    for name in ("disclosure_date", "revision_date"):
        value = _date_text(getattr(version, name, None))
        if value:
            metadata[name] = value
    hint = getattr(document, "download_hint", None)
    if isinstance(hint, dict) and hint:
        metadata["download_hint"] = _sanitize_metadata(hint)
    return metadata


def _sanitize_metadata(value: Any, key: str = "") -> Any:
    """POST 힌트에서 인증·세션 비밀값을 재귀적으로 제거한다."""
    if _SENSITIVE_KEY.search(key):
        return None
    if isinstance(value, dict):
        return {
            str(k): sanitized
            for k, child in value.items()
            if (sanitized := _sanitize_metadata(child, str(k))) is not None
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_metadata(child, key) for child in value]
    if isinstance(value, str):
        # 인증 URL이 평범한 필드명 아래 중첩되는 경우에도 query 비밀값이
        # source_metadata나 POST identity에 남지 않게 한다.
        return _safe_url_locator(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)
