"""판매 상태 재검증과 상태 폴더 이동을 위한 독립적인 핵심 로직.

이 모듈은 보험사 어댑터나 ``ManifestService``에 의존하지 않는다. 호출부는
전역 manifest 행을 ``dict``로 넘기고, 어댑터가 만든 :class:`StatusObservation`을
넘긴 뒤 ``ReconciliationResult``의 제안 결과를 물리적 폴더 이동 결과와 함께
``commit_actions()``로 확정해 manifest에 반영해야 한다. 이동 충돌이 있으면
원래 행을 유지한다. 따라서 상태 확인과 문서 재다운로드를 분리할 수 있고,
상태가 바뀌었다는 이유만으로 PDF를 다시 받지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import stat
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from typing import Iterable, Mapping

from models.product_version import ProductVersion
from models.sale_status import STATUS_PREFIX, SaleStatus, classify_sale_status
from utils.file_utils import normalize_storage_component
from utils.network_io import (
    durable_append_bytes,
    retry_file_operation,
    safe_fsync,
    strict_exists,
    strict_is_file,
)


JOURNAL_SCHEMA_VERSION = 2


def normalize_sale_state(value: object) -> str:
    """보험사별 판매 상태 표현을 ``ACTIVE/ENDED/UNKNOWN``으로 바꾼다."""

    return str(classify_sale_status(value))


def _date_text(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return ""
    # The manifest currently uses ISO strings.  Preserve unknown formats rather
    # than silently changing a source identifier.
    return text


def logical_version_key(row: Mapping[str, object]) -> str:
    """문서 행에서 상태 갱신용 논리 상품 버전 키를 만든다.

    문서 타입/URL은 키에 넣지 않는다. 동일한 상품 버전의 여러 문서가
    하나의 상태 전환으로 함께 이동해야 하기 때문이다.  source id가 없는
    어댑터를 위해 판매개시일·기준일·상품명 순으로 안정적인 대체값을 쓴다.
    """

    company = str(row.get("company_code") or row.get("company_name") or "").strip()
    source_id = str(row.get("source_product_id") or "").strip()
    start = _date_text(row.get("sale_start_date"))
    target = _date_text(row.get("target_date") or row.get("revision_date") or row.get("disclosure_date"))
    product = str(
        row.get("product_name_normalized")
        or row.get("product_name_raw")
        or row.get("product_name")
        or ""
    ).strip()
    return "|".join((company, source_id, start, target, product))


def active_manifest_rows(
    rows: Iterable[Mapping[str, object]], company_code: str = ""
) -> list[dict]:
    """manifest 문서 행을 ACTIVE 논리 버전 대표 행으로 축약한다."""

    wanted = str(company_code or "").strip().upper()
    result: dict[str, dict] = {}
    for source in rows:
        if not isinstance(source, Mapping):
            continue
        row = dict(source)
        code = str(row.get("company_code") or "").strip().upper()
        if wanted and code != wanted:
            continue
        state = normalize_sale_state(
            row.get("normalized_sale_status") or row.get("sale_status")
        )
        if state != SaleStatus.ACTIVE:
            continue
        key = logical_version_key(row)
        # A logical version can have a mixture of document rows (for example
        # one ``NO_DOCUMENT_LINK`` checkpoint row plus successfully saved
        # policy/summary rows).  Prefer a row that actually carries a saved
        # path so the representative used for the folder move can locate the
        # physical version directory.  The reconciliation service still
        # applies the resulting state to every row in the logical group.
        current = result.get(key)
        if current is None or (
            not current.get("saved_relative_path")
            and row.get("saved_relative_path")
        ):
            result[key] = row
    return [result[key] for key in sorted(result)]


def product_version_matches_row(version: ProductVersion, row: Mapping[str, object]) -> bool:
    """수집된 상품 버전이 기존 manifest 논리 버전과 같은지 판정한다."""

    if str(version.company_code or "").strip().upper() != str(
        row.get("company_code") or ""
    ).strip().upper():
        return False
    row_id = str(row.get("source_product_id") or "").strip()
    version_id = str(version.source_product_id or "").strip()
    row_start = _date_text(row.get("sale_start_date"))
    version_start = _date_text(version.sale_start_date)
    if row_id and version_id:
        if row_id != version_id:
            return False
        # Product-level source ids can repeat over many sale periods.
        if row_start and version_start:
            return row_start == version_start
        return not row_start and not version_start

    row_name = str(
        row.get("product_name_normalized")
        or normalize_storage_component(str(row.get("product_name_raw") or ""))
    )
    version_name = normalize_storage_component(version.product_name_raw or "")
    if not row_name or not version_name or row_name != version_name:
        return False
    if row_start and version_start:
        return row_start == version_start
    row_target = _date_text(
        row.get("target_date") or row.get("revision_date") or row.get("disclosure_date")
    )
    version_target = _date_text(version.target_date)
    return bool(row_target and version_target and row_target == version_target)


def observations_from_versions(
    active_rows: Iterable[Mapping[str, object]],
    versions: Iterable[ProductVersion],
    *,
    coverage_complete: bool,
    observed_at: str = "",
    source: str = "",
) -> dict[str, "StatusObservation"]:
    """한 번 수집한 버전 목록을 기존 ACTIVE 행의 상태 관찰로 변환한다."""

    candidates = list(versions)
    observations: dict[str, StatusObservation] = {}
    for row in active_rows:
        key = logical_version_key(row)
        matches = [version for version in candidates if product_version_matches_row(version, row)]
        if not matches:
            continue
        states = {str(version.normalized_sale_status) for version in matches}
        if len(states) > 1:
            # A duplicated logical row can be materialized from multiple tabs
            # or pages.  Conflicting states are evidence of an ambiguous
            # response, never a reason to move an existing folder.  Mark the
            # observation unusable so reconciliation preserves the prior row.
            observations[key] = StatusObservation(
                state=SaleStatus.UNKNOWN,
                source=source,
                coverage_complete=False,
                request_ok=False,
                found=False,
                observed_at=observed_at,
                error="conflicting_status_observations",
            )
            continue
        # Prefer a match carrying an explicit end date when duplicate rows
        # agree on state; it gives manifest enrichment deterministic input.
        match = max(matches, key=lambda version: version.sale_end_date is not None)
        observations[key] = StatusObservation(
            state=str(match.normalized_sale_status),
            raw_status=match.sale_status,
            sale_end_date=match.sale_end_date,
            source=source or match.company_code,
            coverage_complete=coverage_complete,
            request_ok=True,
            found=True,
            observed_at=observed_at,
        )
    return observations


@dataclass(frozen=True)
class StatusObservation:
    """어댑터가 한 번의 상태 확인에서 반환하는 결과.

    ``coverage_complete=False`` 또는 ``request_ok=False``이면 해당 회사의
    목록이 완전하지 않으므로 기존 상태를 절대 변경하지 않는다.  완전한
    목록에서 상품이 사라진 경우에는 ``found=False``인 관찰을 직접 넣거나
    company_coverage를 통해 부재를 계산할 수 있다.
    """

    state: str
    raw_status: str = ""
    sale_end_date: str | date | None = None
    source: str = ""
    coverage_complete: bool = True
    request_ok: bool = True
    found: bool = True
    observed_at: str = ""
    error: str = ""

    @property
    def usable(self) -> bool:
        return bool(self.request_ok and self.coverage_complete)

    @property
    def normalized_state(self) -> str:
        return normalize_sale_state(self.state)


@dataclass
class ReconciliationAction:
    key: str
    old_state: str
    new_state: str
    old_path: str = ""
    new_path: str = ""
    reason: str = ""
    sale_end_date: str = ""
    raw_status: str = ""
    source: str = ""
    move_required: bool = False
    missing_count: int = 0
    dry_run: bool = False


@dataclass
class ReconciliationResult:
    updated_rows: list[dict] = field(default_factory=list)
    actions: list[ReconciliationAction] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    # ``updated_rows`` is a proposal.  Call ``commit_actions`` after the
    # physical folder move has succeeded so conflicts do not leak into the
    # manifest.
    original_rows: list[dict] = field(default_factory=list, repr=False)

    def commit_actions(self, outcomes: Mapping[str, object] | None = None) -> list[dict]:
        outcomes = outcomes or {}
        rows = [dict(row) for row in self.updated_rows]
        originals = self.original_rows or [dict(row) for row in rows]
        for action in self.actions:
            if not action.move_required:
                continue
            outcome = outcomes.get(action.key)
            success = bool(outcome is True or str(getattr(outcome, "phase", "")) in {"MOVED", "COMMITTED"})
            indexes = [i for i, row in enumerate(rows) if logical_version_key(row) == action.key]
            if not success:
                for index in indexes:
                    if index < len(originals):
                        rows[index] = dict(originals[index])
                continue
            destination = str(getattr(outcome, "destination", "") or action.new_path)
            for index in indexes:
                value = str(rows[index].get("saved_relative_path") or "")
                if value:
                    rows[index]["saved_relative_path"] = _replace_path_prefix(value, action.new_path, destination)
        return rows


class StatusReconciliationService:
    """manifest 행과 새 상태 관찰을 deterministic하게 병합한다."""

    def __init__(self, *, missing_threshold: int = 2, dry_run: bool = False):
        if missing_threshold < 2:
            raise ValueError("missing_threshold는 2 이상이어야 합니다")
        self.missing_threshold = missing_threshold
        self.dry_run = dry_run

    def reconcile(
        self,
        rows: Iterable[Mapping[str, object]],
        observations: Mapping[str, StatusObservation] | None = None,
        *,
        company_coverage: Mapping[str, bool] | None = None,
        observed_at: str | None = None,
    ) -> ReconciliationResult:
        """논리 버전별 상태를 갱신한다.

        ``observations`` 키는 :func:`logical_version_key` 값이다.  관찰이
        없는 키는 해당 회사 coverage가 완전할 때만 누락으로 간주한다.
        결과 행은 입력 순서와 문서 행 순서를 유지한다.
        """

        original = [dict(row) for row in rows]
        grouped: dict[str, list[int]] = {}
        for index, row in enumerate(original):
            grouped.setdefault(logical_version_key(row), []).append(index)
        observations = observations or {}
        company_coverage = company_coverage or {}
        out = [dict(row) for row in original]
        actions: list[ReconciliationAction] = []
        counts = {
            "candidates": 0,
            "still_active": 0,
            "ended": 0,
            "unknown": 0,
            "missing_grace": 0,
            "partial_or_failed": 0,
            "unchanged": 0,
        }

        for key in sorted(grouped):
            indexes = grouped[key]
            representative = out[indexes[0]]
            old_state = normalize_sale_state(
                representative.get("normalized_sale_status") or representative.get("sale_status")
            )
            # A row already recorded as ended/unknown is not an ACTIVE refresh
            # candidate.  It may still receive an explicit corrective ACTIVE
            # observation, which is intentionally supported below.
            is_candidate = old_state == SaleStatus.ACTIVE
            if is_candidate:
                counts["candidates"] += 1

            observation = observations.get(key)
            company = str(representative.get("company_code") or representative.get("company_name") or "")
            if observation is None:
                if not is_candidate or not company_coverage.get(company, False):
                    counts["unchanged"] += 1
                    continue
                observation = StatusObservation(
                    state=SaleStatus.UNKNOWN,
                    found=False,
                    coverage_complete=True,
                    request_ok=True,
                    observed_at=observed_at or "",
                )

            if not observation.usable:
                counts["partial_or_failed"] += 1
                continue

            if observation.found:
                new_state = observation.normalized_state
                missing_count = 0
                reason = "explicit_observation"
            elif not is_candidate:
                # Missing ended/unknown versions do not get resurrected or
                # modified solely because a later list does not contain them.
                counts["unchanged"] += 1
                continue
            else:
                previous_missing = _int_value(representative.get("status_missing_count"))
                missing_count = previous_missing + 1
                if missing_count >= self.missing_threshold:
                    new_state = SaleStatus.UNKNOWN
                    reason = "consecutive_complete_absence"
                else:
                    new_state = old_state
                    reason = "first_complete_absence_grace"

            old_path = _version_dir_for_row(representative)
            # 상태가 그대로여도 layout v1의 무접두사 폴더는 현재 canonical
            # prefix로 한 번 이동한다. 이미 올바른 prefix면 같은 경로다.
            new_path = status_prefixed_path(old_path, new_state) if old_path else old_path
            move = bool(old_path and new_path != old_path)
            action = ReconciliationAction(
                key=key,
                old_state=old_state,
                new_state=new_state,
                old_path=old_path,
                new_path=new_path,
                reason=reason,
                sale_end_date=_date_text(observation.sale_end_date),
                raw_status=observation.raw_status,
                source=observation.source,
                move_required=move,
                missing_count=missing_count,
                dry_run=self.dry_run,
            )
            if old_state != new_state or move or observation.found or missing_count:
                actions.append(action)

            for index in indexes:
                row = out[index]
                if observation.found or new_state != old_state or missing_count:
                    row["normalized_sale_status"] = new_state
                    row["status_missing_count"] = missing_count
                    row["status_check_result"] = "CONFIRMED" if observation.found else "MISSING"
                    row["status_checked_at"] = observation.observed_at or observed_at or _now()
                    if observation.raw_status:
                        row["sale_status"] = observation.raw_status
                        row["source_sale_status"] = observation.raw_status
                    if observation.source:
                        row["status_source"] = observation.source
                    if observation.sale_end_date is not None:
                        row["sale_end_date"] = _date_text(observation.sale_end_date)
                    if new_state != old_state:
                        row["status_changed_at"] = observation.observed_at or observed_at or _now()
                    if move:
                        if row.get("saved_relative_path"):
                            row["saved_relative_path"] = _replace_path_prefix(str(row["saved_relative_path"]), old_path, new_path)

            if new_state == SaleStatus.ACTIVE:
                counts["still_active"] += 1
            elif new_state == SaleStatus.ENDED:
                counts["ended"] += 1
            elif new_state == SaleStatus.UNKNOWN:
                counts["unknown"] += 1
            if reason == "first_complete_absence_grace":
                counts["missing_grace"] += 1

        return ReconciliationResult(updated_rows=out, actions=actions, stats=counts, original_rows=original)


def _version_dir_for_row(row: Mapping[str, object]) -> str:
    """문서 파일 경로에서 상태가 붙는 상품 버전 폴더를 추출한다."""

    relative = str(row.get("saved_relative_path") or "")
    saved_name = str(row.get("saved_filename") or "").strip()
    if relative:
        path = Path(relative)
        if saved_name and path.name == saved_name:
            return str(path.parent)
        if path.suffix.lower() in {".pdf", ".doc", ".docx", ".hwp", ".txt", ".xlsx", ".xls"}:
            return str(path.parent)
        return str(path)
    return ""


def _int_value(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def status_prefixed_path(path: str | Path, state: str) -> str:
    """경로의 마지막 폴더에 상태 prefix를 적용한다."""

    raw = str(path or "")
    if not raw:
        return raw
    try:
        prefix = STATUS_PREFIX[SaleStatus(normalize_sale_state(state))]
    except ValueError:
        prefix = STATUS_PREFIX[SaleStatus.UNKNOWN]
    p = Path(raw)
    name = p.name
    for known in STATUS_PREFIX.values():
        if name.startswith(known):
            name = name[len(known) :]
            break
    name = prefix + name
    return str(p.with_name(name))


def _replace_path_prefix(value: str, old: str, new: str) -> str:
    if value == old:
        return new
    old_name = Path(old).name
    if old_name:
        # Replace the directory component, not only an exact full-path match.
        value_path = Path(value)
        parts = list(value_path.parts)
        for index, part in enumerate(parts):
            if part == old_name:
                parts[index] = Path(new).name
                try:
                    return str(Path(*parts))
                except (TypeError, ValueError):
                    break
    return value.replace(old, new, 1)


def replace_status_folder_path(value: str, old: str | Path, new: str | Path) -> str:
    """manifest 파일 경로에서 상태 상품폴더 구성요소만 교체한다."""

    return _replace_path_prefix(str(value or ""), str(old or ""), str(new or ""))


@dataclass
class RenameEvent:
    action_id: str
    phase: str
    source: str
    destination: str
    timestamp: str
    error: str = ""
    reused: bool = False
    logical_key: str = ""
    old_state: str = ""
    new_state: str = ""
    schema_version: int = JOURNAL_SCHEMA_VERSION


class RenameJournal:
    """fsync되는 JSONL 이동 저널.

    한 줄씩 append하므로 PLANNED/MOVED/COMMITTED 중간에 프로세스가
    종료되어도 ``recover``가 같은 작업을 다시 보고 idempotently 정리할 수
    있다. 운영 루트에서는 ``99_운영/state/status/{보험사코드}/folder_moves.v2.jsonl``를
    넘긴다.
    """

    def __init__(self, path: Path, *, output_root: Path | None = None):
        self.path = Path(path)
        self.output_root = Path(output_root).resolve() if output_root else None

    def _store_path(self, value: str | Path) -> str:
        path = Path(value)
        if self.output_root is None:
            return path.as_posix()
        try:
            rel = path.resolve(strict=False).relative_to(self.output_root)
        except (OSError, ValueError) as exc:
            raise ValueError("journal 경로가 output root 밖에 있습니다") from exc
        return rel.as_posix()

    def _load_path(self, value: str) -> str:
        if self.output_root is None:
            return value
        if Path(value).is_absolute() or PureWindowsPath(value).is_absolute() or PureWindowsPath(value).drive:
            raise ValueError("journal에는 상대 경로만 허용됩니다")
        rel = PurePosixPath(value.replace("\\", "/"))
        if not value or rel.is_absolute() or ".." in rel.parts:
            raise ValueError("journal 경로 traversal")
        candidate = (self.output_root / Path(*rel.parts)).resolve(strict=False)
        try:
            candidate.relative_to(self.output_root)
        except ValueError as exc:
            raise ValueError("journal 경로가 output root 밖에 있습니다") from exc
        return str(candidate)

    def append(self, event: RenameEvent) -> None:
        retry_file_operation(
            lambda: self.path.parent.mkdir(parents=True, exist_ok=True),
            path=self.path.parent,
            operation_name="상태 journal 디렉터리 생성",
        )
        payload = dict(event.__dict__)
        payload["source"] = self._store_path(payload["source"])
        payload["destination"] = self._store_path(payload["destination"])
        durable_append_bytes(
            self.path,
            (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"),
        )

    def events(self) -> list[RenameEvent]:
        if not _retry_exists(self.path):
            return []
        result: list[RenameEvent] = []
        raw = retry_file_operation(
            self.path.read_bytes,
            path=self.path,
            operation_name="상태 journal 읽기",
        )
        text = raw.decode("utf-8")
        lines = text.splitlines(keepends=True)
        for index, line in enumerate(lines):
            final_torn = index == len(lines) - 1 and not line.endswith(("\n", "\r"))
            try:
                data = json.loads(line.rstrip("\r\n"))
                required = ("action_id", "phase", "source", "destination", "timestamp")
                if (
                    not isinstance(data, dict)
                    or any(not isinstance(data.get(key), str) or not data.get(key) for key in required)
                    or data.get("phase") not in {"PLANNED", "MOVED", "COMMITTED", "FAILED", "CONFLICT"}
                    or int(data.get("schema_version", 0)) != JOURNAL_SCHEMA_VERSION
                ):
                    raise ValueError("필수 상태 이동 저널 필드가 없습니다")
                data["source"] = self._load_path(data["source"])
                data["destination"] = self._load_path(data["destination"])
                result.append(RenameEvent(**{k: data.get(k, "") for k in RenameEvent.__dataclass_fields__}))
            except (json.JSONDecodeError, TypeError) as exc:
                if not final_torn:
                    raise ValueError(
                        f"손상된 상태 이동 저널 행입니다: {self.path}:{index + 1}"
                    ) from exc
                # Process termination may leave only the final JSONL row
                # without a newline.  Middle/newline-terminated corruption
                # is unsafe and must stop recovery.
                valid_end = sum(len(item.encode("utf-8")) for item in lines[:index])
                def truncate() -> None:
                    with self.path.open("r+b") as fp:
                        fp.truncate(valid_end)
                        fp.flush()
                        safe_fsync(fp, path=self.path)
                retry_file_operation(truncate, path=self.path, operation_name="상태 journal torn tail 복구")
                break
            except ValueError:
                # Valid JSON with an invalid event shape is not a torn write.
                raise
            if index == len(lines) - 1 and not line.endswith(("\n", "\r")):
                # Keep append-only JSONL valid when a clean writer omitted the
                # final newline.  Match the existing file's line ending.
                ending = b"\r\n" if b"\r\n" in raw else b"\n"
                durable_append_bytes(self.path, ending)
        return result


@dataclass
class RenameResult:
    action_id: str
    source: Path
    destination: Path
    phase: str
    reused: bool = False
    conflict: bool = False
    error: str = ""
    logical_key: str = ""
    old_state: str = ""
    new_state: str = ""


class StatusFolderMover:
    """상태 전환 폴더의 안전한 same-volume rename 구현."""

    def __init__(self, journal: RenameJournal, *, documents_root: Path | None = None, dry_run: bool = False):
        self.journal = journal
        self.documents_root = Path(documents_root).resolve() if documents_root else None
        if self.journal.output_root is None and self.documents_root is not None:
            self.journal.output_root = self.documents_root.parent
        self.dry_run = dry_run

    def move(
        self,
        source: Path,
        destination: Path,
        *,
        action_id: str | None = None,
        logical_key: str = "",
        old_state: str = "",
        new_state: str = "",
    ) -> RenameResult:
        source, destination = Path(source), Path(destination)
        self._validate(source, destination)
        action_id = action_id or uuid.uuid4().hex
        if source == destination:
            return RenameResult(action_id, source, destination, "COMMITTED")
        source_exists = _retry_exists(source)
        destination_exists = _retry_exists(destination)
        if not source_exists and destination_exists:
            return RenameResult(action_id, source, destination, "CONFLICT", conflict=True, error="source_missing_existing_destination", logical_key=logical_key, old_state=old_state, new_state=new_state)
        if not source_exists:
            return RenameResult(action_id, source, destination, "FAILED", error="source_missing")

        destination_is_dir = _retry_is_dir(destination) if destination_exists else False
        source_is_dir = _retry_is_dir(source) if source_exists else False
        if destination_exists and destination_is_dir and source_is_dir and _tree_digest(source) == _tree_digest(destination):
            # The content is reusable, but two physical product folders would
            # remain if we silently committed the manifest update.  Keep both
            # untouched and require an explicit merge decision from the caller.
            self.journal.append(RenameEvent(action_id, "PLANNED", str(source), str(destination), _now(), reused=True, logical_key=logical_key, old_state=old_state, new_state=new_state))
            self.journal.append(RenameEvent(action_id, "CONFLICT", str(source), str(destination), _now(), error="identical_destination_exists", reused=True, logical_key=logical_key, old_state=old_state, new_state=new_state))
            return RenameResult(action_id, source, destination, "CONFLICT", reused=True, conflict=True, error="identical_destination_exists")

        actual_destination = self._collision_destination(source, destination)
        event = RenameEvent(action_id, "PLANNED", str(source), str(actual_destination), _now(), logical_key=logical_key, old_state=old_state, new_state=new_state)
        self.journal.append(event)
        if self.dry_run:
            return RenameResult(action_id, source, actual_destination, "PLANNED", reused=event.reused)
        try:
            retry_file_operation(
                lambda: actual_destination.parent.mkdir(parents=True, exist_ok=True),
                path=actual_destination.parent,
                operation_name="판매상태 대상 디렉터리 생성",
            )
            if _retry_exists(actual_destination):
                raise FileExistsError(str(actual_destination))
            self._same_volume(source, actual_destination.parent)
            retry_file_operation(
                lambda: source.rename(actual_destination),
                path=actual_destination,
                operation_name="판매상태 폴더 이동",
            )
        except (OSError, ValueError) as exc:
            self.journal.append(RenameEvent(action_id, "FAILED", str(source), str(actual_destination), _now(), error=str(exc), logical_key=logical_key, old_state=old_state, new_state=new_state))
            return RenameResult(action_id, source, actual_destination, "FAILED", error=str(exc))
        self.journal.append(RenameEvent(action_id, "MOVED", str(source), str(actual_destination), _now(), logical_key=logical_key, old_state=old_state, new_state=new_state))
        return RenameResult(action_id, source, actual_destination, "MOVED", logical_key=logical_key, old_state=old_state, new_state=new_state)

    def finalize(self, result_or_action_id: RenameResult | str) -> bool:
        """manifest 원자 write가 성공한 뒤 이동을 확정한다."""

        action_id = result_or_action_id.action_id if isinstance(result_or_action_id, RenameResult) else str(result_or_action_id)
        events = [event for event in self.journal.events() if event.action_id == action_id]
        if not events:
            return False
        if any(event.phase == "COMMITTED" for event in events):
            return True
        moved = next((event for event in reversed(events) if event.phase == "MOVED"), None)
        if moved is None:
            return False
        self.journal.append(RenameEvent(action_id, "COMMITTED", moved.source, moved.destination, _now(), logical_key=moved.logical_key, old_state=moved.old_state, new_state=moved.new_state))
        return True

    def recover(self) -> list[RenameResult]:
        grouped: dict[str, list[RenameEvent]] = {}
        for event in self.journal.events():
            grouped.setdefault(event.action_id, []).append(event)
        result: list[RenameResult] = []
        for action_id, events in grouped.items():
            if any(event.phase in {"COMMITTED", "FAILED", "CONFLICT"} for event in events):
                continue
            event = events[-1]
            source, destination = Path(event.source), Path(event.destination)
            self._validate(source, destination)
            source_exists = _retry_exists(source)
            destination_exists = _retry_exists(destination)
            if not source_exists and destination_exists:
                self.journal.append(
                    RenameEvent(
                        action_id,
                        "MOVED",
                        str(source),
                        str(destination),
                        _now(),
                        logical_key=event.logical_key,
                        old_state=event.old_state,
                        new_state=event.new_state,
                    )
                )
                result.append(RenameResult(action_id, source, destination, "MOVED", logical_key=event.logical_key, old_state=event.old_state, new_state=event.new_state))
            elif source_exists and not destination_exists:
                moved = self.move(source, destination, action_id=action_id, logical_key=event.logical_key, old_state=event.old_state, new_state=event.new_state)
                result.append(moved)
            elif source_exists and destination_exists:
                result.append(RenameResult(action_id, source, destination, "CONFLICT", conflict=True, error="both_paths_exist", logical_key=event.logical_key, old_state=event.old_state, new_state=event.new_state))
            else:
                result.append(RenameResult(action_id, source, destination, "PENDING", error="both_paths_missing"))
        return result

    def _validate(self, source: Path, destination: Path) -> None:
        if self.documents_root is None:
            return
        root = self.documents_root
        for candidate in (source.resolve(), destination.resolve()):
            if candidate != root and root not in candidate.parents:
                raise ValueError(f"documents_root 밖의 경로입니다: {candidate}")

    @staticmethod
    def _same_volume(source: Path, destination_parent: Path) -> None:
        try:
            source_dev = retry_file_operation(
                lambda: source.stat().st_dev,
                path=source,
                operation_name="상태 폴더 source volume 확인",
            )
            destination_dev = retry_file_operation(
                lambda: destination_parent.stat().st_dev,
                path=destination_parent,
                operation_name="상태 폴더 destination volume 확인",
            )
            if source_dev != destination_dev:
                raise OSError("source와 destination이 서로 다른 파일시스템입니다")
        except FileNotFoundError:
            # Parent is created before this check; keep a useful error if it
            # disappeared concurrently.
            raise

    @staticmethod
    def _collision_destination(source: Path, destination: Path) -> Path:
        if not _retry_exists(destination):
            return destination
        stem, suffix = destination.name, 2
        while True:
            candidate = destination.with_name(f"{stem}_{suffix}")
            if not _retry_exists(candidate):
                return candidate
            suffix += 1


def _tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    if not _retry_is_dir(path):
        return digest.hexdigest()
    children = retry_file_operation(
        lambda: sorted(path.rglob("*")),
        path=path,
        operation_name="상태 폴더 내용 열거",
    )
    for child in children:
        is_file = retry_file_operation(
            lambda child=child: strict_is_file(child),
            path=child,
            operation_name="상태 폴더 파일 형식 확인",
        )
        if is_file:
            digest.update(str(child.relative_to(path)).replace("\\", "/").encode())
            payload = retry_file_operation(
                child.read_bytes,
                path=child,
                operation_name="상태 폴더 파일 읽기",
            )
            digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()


def _retry_exists(path: Path) -> bool:
    """상태 폴더 검사도 네트워크 저장소의 일시 오류를 재시도한다."""
    return retry_file_operation(
        lambda: strict_exists(path),
        path=path,
        operation_name="상태 폴더 존재 확인",
    )


def _retry_is_dir(path: Path) -> bool:
    """네트워크 stat 오류를 폴더 부재로 오판하지 않고 재시도한다."""

    return retry_file_operation(
        lambda: stat.S_ISDIR(path.stat().st_mode),
        path=path,
        operation_name="상태 폴더 형식 확인",
    )


__all__ = [
    "StatusObservation",
    "StatusReconciliationService",
    "ReconciliationAction",
    "ReconciliationResult",
    "RenameEvent",
    "RenameJournal",
    "RenameResult",
    "StatusFolderMover",
    "active_manifest_rows",
    "logical_version_key",
    "normalize_sale_state",
    "observations_from_versions",
    "product_version_matches_row",
    "replace_status_folder_path",
    "status_prefixed_path",
]
