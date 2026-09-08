"""저장 경로 검증 및 생성.

신규 출력 구조는 사람이 문서를 찾는 영역과 실행 내부 상태를 분리한다.

    {BASE_OUTPUT_PATH}/{ROOT_FOLDER}/
        01_문서/{보험사}/{연도}/{월}/{판매상태}__{기준일}_{상품명}/{문서명}.{확장자}
        99_운영/{state,runs,locks}/...

다운로드 검증 전 staging은 네트워크 출력 시 로컬 TEMP 아래의 출력별 격리
경로를 사용하고, 로컬 출력 테스트/개발에서만 ``99_운영/staging``을
사용한다.

수집 문서 상태는 PostgreSQL repository가 정본이다. 실행별 plan·checkpoint와
상태 이동 저널만 ``99_운영`` 아래에 저장한다.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from models.document import DocumentType
from models.product_version import ProductVersion
from models.sale_status import status_prefix
from utils.date_utils import period_scope_key
from utils.file_utils import normalize_extension, normalize_storage_component, split_extension
from utils.crawler_logger import get_logger
from utils.network_io import (
    configure_network_path,
    is_network_path,
    retry_file_operation,
    strict_is_dir,
    strict_exists,
)


class NetworkPathError(RuntimeError):
    """파일 서버 접근 실패."""

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(reason)

    def format_message(self) -> str:
        return (
            "[ERROR] 파일 서버에 접근할 수 없습니다.\n"
            f"경로: {self.path}\n"
            f"원인: {self.reason}"
        )


@dataclass
class PathService:
    base_path: str
    root_folder: str
    target_month: str = ""
    max_path_length: int = 240
    # 기간 실행에서는 월 대신 이 식별자를 사용한다. 단월 실행은
    # target_month 값을 동일한 scope로 사용한다.
    scope_key: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    # ``auto``는 Windows UNC를 자동 감지하고, ``smb``는 /data 같은 Linux
    # bind mount에도 동일한 네트워크 I/O 정책을 명시적으로 적용한다.
    storage_kind: str = "auto"
    local_staging_override: str | Path | None = None
    local_state_override: str | Path | None = None

    def __post_init__(self) -> None:
        self.storage_kind = str(self.storage_kind or "auto").strip().lower()
        if self.storage_kind not in {"auto", "local", "smb"}:
            raise ValueError(f"지원하지 않는 저장소 모드입니다: {self.storage_kind}")
        if self.storage_kind == "smb":
            # network_io의 모든 helper가 /data 하위 경로를 네트워크 경로로
            # 처리하도록 등록한다(다운로드/lock/outbox/checkpoint 포함).
            configure_network_path(self.output_root)

    @property
    def scope_component(self) -> str:
        """실행 plan/checkpoint 경로에 사용할 정규화된 범위."""
        if self.scope_key:
            return self.scope_key
        if self.period_start is not None and self.period_end is not None:
            return period_scope_key(self.period_start, self.period_end)
        return self.target_month

    # ------------------------------------------------------------------
    # 경로 검증
    # ------------------------------------------------------------------
    def verify_base_path(self) -> Path:
        """실행 전 파일 서버 접근성을 검증한다.

        1) 네트워크 경로 접근 가능 여부
        2) 디렉터리 존재 여부
        3) 쓰기 권한 여부
        4) 테스트 파일 생성/삭제 가능 여부

        실패 시 NetworkPathError 를 발생시킨다. 로컬로 대체 저장하지 않는다.
        """
        raw = (self.base_path or "").strip()
        if not raw:
            raise NetworkPathError("(설정 없음)", "config.yaml 의 output.base_path 가 비어 있습니다")

        base = Path(raw)

        # 1) 접근 가능 여부
        try:
            exists = retry_file_operation(
                lambda: strict_exists(base),
                path=self.output_root,
                operation_name="출력 루트 존재 확인",
            )
        except OSError as exc:
            raise NetworkPathError(raw, f"네트워크 연결 실패 또는 접근 권한 없음 ({exc.strerror or exc})") from exc
        if not exists:
            raise NetworkPathError(raw, "접근 권한 없음 또는 네트워크 연결 실패 (경로를 찾을 수 없음)")

        # 2) 디렉터리 여부
        if not retry_file_operation(
            lambda: strict_is_dir(base),
            path=self.output_root,
            operation_name="출력 루트 디렉터리 확인",
        ):
            raise NetworkPathError(raw, "경로가 디렉터리가 아닙니다")

        # 3) 실제 출력 루트에 probe를 만들어 쓰기/읽기/삭제를 검증한다.
        output_root = self.output_root
        try:
            retry_file_operation(
                lambda: output_root.mkdir(parents=True, exist_ok=True),
                path=output_root,
                operation_name="출력 루트 생성",
            )
        except OSError as exc:
            raise NetworkPathError(raw, f"출력 루트 생성 실패 ({exc.strerror or exc})") from exc
        probe = output_root / f".write_test_{uuid.uuid4().hex}.tmp"
        try:
            retry_file_operation(
                lambda: probe.write_bytes(b"ok"),
                path=probe,
                operation_name="출력 루트 쓰기 probe",
            )
            if retry_file_operation(
                probe.read_bytes,
                path=probe,
                operation_name="출력 루트 읽기 probe",
            ) != b"ok":
                raise OSError("테스트 파일 내용 검증 실패")
        except OSError as exc:
            raise NetworkPathError(raw, f"테스트 파일 생성 실패 ({exc.strerror or exc})") from exc
        finally:
            try:
                retry_file_operation(
                    lambda: probe.unlink(missing_ok=True),
                    path=probe,
                    operation_name="출력 루트 probe 정리",
                )
            except OSError as exc:
                raise NetworkPathError(raw, f"테스트 파일 삭제 실패 ({exc.strerror or exc})") from exc

        return base

    # ------------------------------------------------------------------
    # 경로 구성
    # ------------------------------------------------------------------
    @property
    def output_root(self) -> Path:
        """문서와 실행 메타데이터가 저장되는 최상위 폴더."""
        return Path(self.base_path) / self.root_folder

    def resolve_relative_path(self, relative_path: str | Path) -> Path:
        """출력 루트 안의 상대경로만 해석한다.

        DB/plan/summary에 저장되는 경로는 POSIX 상대경로여야 하며,
        절대경로와 ``..``를 통한 출력 루트 탈출은 즉시 거부한다.
        """
        text = str(relative_path).replace("\\", "/")
        candidate = Path(text)
        if (
            candidate.is_absolute()
            or candidate.anchor
            or PurePosixPath(text).is_absolute()
            or PureWindowsPath(text).is_absolute()
            or bool(PureWindowsPath(text).drive)
        ):
            raise ValueError(f"출력 루트 기준 상대경로가 아닙니다: {relative_path!r}")
        root = self.output_root.resolve()
        resolved = (root / candidate).resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"출력 루트 밖의 경로입니다: {relative_path!r}")
        return resolved

    def relative_output_path(self, path: str | Path) -> str:
        """물리 경로를 출력 루트 기준 POSIX 상대경로로 정규화한다."""
        root = self.output_root.resolve()
        candidate = Path(path).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError(f"출력 루트 밖의 경로입니다: {path!r}")
        return candidate.relative_to(root).as_posix()

    @property
    def documents_root(self) -> Path:
        """사람이 탐색하는 검증 완료 문서의 루트."""
        return self.output_root / "01_문서"

    @property
    def operations_root(self) -> Path:
        """크롤러 내부 상태를 모아 두는 루트."""
        return self.output_root / "99_운영"

    @property
    def state_root(self) -> Path:
        return self.operations_root / "state"

    @property
    def staging_root(self) -> Path:
        return self.operations_root / "staging"

    @property
    def is_network_output(self) -> bool:
        if self.storage_kind == "smb":
            return True
        if self.storage_kind == "local":
            return False
        return is_network_path(self.output_root)

    @property
    def local_staging_root(self) -> Path:
        """다운로드 검증 전 임시 파일을 둘 로컬 staging 루트.

        로컬 출력 테스트/개발에서는 기존 ``99_운영/staging``을 유지한다.
        네트워크 출력에서는 사용자 TEMP 아래에 출력 루트별 격리 디렉터리를
        만들어 cross-volume publish 전 검증을 수행한다.
        """
        if self.local_staging_override:
            return Path(self.local_staging_override)
        if not self.is_network_output:
            return self.staging_root
        identity = hashlib.sha256(str(self.output_root).encode("utf-8")).hexdigest()[:16]
        candidates = [Path(tempfile.gettempdir())]
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            candidates.append(Path(local_app_data) / "Temp")
        # TEMP가 회사 정책으로 네트워크 드라이브에 매핑된 경우에도 프로젝트가 있는
        # 로컬 디스크를 마지막 fallback으로 사용한다.
        candidates.append(Path(__file__).resolve().parents[1] / ".local_staging")
        local_root = next((candidate for candidate in candidates if not is_network_path(candidate)), None)
        if local_root is None:
            raise RuntimeError("로컬 staging 디스크를 찾을 수 없습니다 (TEMP가 모두 네트워크 경로입니다)")
        return local_root / "insurance-document-crawler" / identity / "staging"

    @property
    def local_state_root(self) -> Path:
        """DB outbox 등 출력 루트와 독립적인 로컬 영속 상태 루트.

        staging과 달리 TEMP를 사용하지 않는다. ``LOCALAPPDATA``가 비어
        있거나 네트워크 경로로 매핑된 경우 저장소 내부의 ``.local_state``를 사용한다.
        출력 루트 해시를 포함해 서로 다른 출력 대상의 상태가 섞이지 않는다.
        """
        if self.local_state_override:
            return Path(self.local_state_override)
        identity = hashlib.sha256(str(self.output_root).encode("utf-8")).hexdigest()[:16]
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        local_root = (
            Path(local_app_data)
            if local_app_data
            else Path(__file__).resolve().parents[1] / ".local_state"
        )
        if is_network_path(local_root):
            local_root = Path(__file__).resolve().parents[1] / ".local_state"
        return local_root / "insurance-document-crawler" / identity / "state"

    @property
    def runs_root(self) -> Path:
        return self.operations_root / "runs"

    @property
    def locks_root(self) -> Path:
        return self.operations_root / "locks"

    def run_dir(self, run_id: str) -> Path:
        """실행별 산출물 경로.

        run id는 ``YYYYMMDD...``로 시작해야 하며 날짜가 없거나 유효하지
        않으면 거부한다. 따라서 실행 summary는 날짜별 트리에만 기록된다.
        """
        safe_run_id = normalize_storage_component(run_id)
        day_root = self._run_date_root(run_id)
        return self.runs_root / day_root / safe_run_id

    def run_journal_path(self, run_id: str, company_code: str) -> Path:
        """실행 감사 이벤트 JSONL 경로(문서 정본이 아님)."""
        name = f"{normalize_storage_component(company_code.upper())}.jsonl"
        return self.run_dir(run_id) / "events" / name

    @staticmethod
    def _run_date_root(run_id: str) -> Path:
        text = str(run_id or "")
        if len(text) < 8 or not text[:8].isdigit():
            raise ValueError(f"run_id에 YYYYMMDD 접두사가 필요합니다: {run_id!r}")
        try:
            parsed = datetime.strptime(text[:8], "%Y%m%d")
        except ValueError as exc:
            raise ValueError(f"run_id 날짜가 올바르지 않습니다: {run_id!r}") from exc
        return Path(f"{parsed:%Y}") / f"{parsed:%m}" / f"{parsed:%d}"

    def lock_path(self, company_code: str) -> Path:
        """회사 문서 폴더 전체를 보호하는 보험사 단위 잠금 경로."""
        return self.locks_root / f"{normalize_storage_component(company_code.upper())}.lock"

    def state_dir(self, scope: str | None = None, company_code: str | None = None) -> Path:
        """상품 상세 체크포인트·다운로드 상태의 실행 범위별 경로."""
        scope_component = normalize_storage_component(scope or self.scope_component)
        if company_code:
            return self.state_root / scope_component / normalize_storage_component(company_code.upper())
        return self.state_root / scope_component

    def checkpoint_path(
        self, scope: str | None, company_code: str, filename: str = "detail_checkpoint.v2.jsonl"
    ) -> Path:
        """상품 상세 체크포인트 파일 경로."""
        return self.state_dir(scope, company_code) / normalize_storage_component(filename)

    def status_state_dir(self, company_code: str) -> Path:
        """기간 scope와 무관하게 이어지는 판매상태 재검증 상태 경로."""

        return self.state_root / "status" / normalize_storage_component(company_code.upper())

    def status_move_journal_path(self, company_code: str) -> Path:
        """판매상태 폴더 이동의 crash-recovery JSONL 경로."""

        return self.status_state_dir(company_code) / "folder_moves.v2.jsonl"

    def db_outbox_path(self, company_code: str) -> Path:
        """DB 반영 실패 이벤트를 보관하는 회사별 append-only 경로."""
        # DB 장애 시에도 파일 서버와 TEMP staging에 독립적으로
        # 이벤트를 보존한다. local_state_root는 output_root hash로
        # 격리되어 다른 수집과 충돌하지 않는다.
        return (
            self.local_state_root
            / "db_outbox"
            / f"{normalize_storage_component(company_code.upper())}.jsonl"
        )

    def download_staging_dir(self, run_id: str, company_code: str) -> Path:
        """다운로드 검증 전 임시 파일의 실제 로컬 경로."""
        return self.local_staging_root / normalize_storage_component(run_id) / normalize_storage_component(company_code.upper())

    def server_upload_staging_dir(self, run_id: str, company_code: str) -> Path:
        """파일 서버에 복사한 뒤 최종 이동하기 전의 staging 경로."""
        return self.staging_root / normalize_storage_component(run_id) / normalize_storage_component(company_code.upper())

    def company_dir(self, storage_name: str) -> Path:
        return self.documents_root / self._safe_component(storage_name)

    def version_dir(self, version: ProductVersion) -> Path:
        """상품 버전의 사람이 읽는 문서 폴더."""
        if not str(version.storage_name or "").strip():
            raise ValueError("ProductVersion.storage_name이 비어 있습니다")
        company = self.company_dir(version.storage_name)
        target = version.target_date
        product = self._safe_component(version.product_name_raw or "상품")
        state_prefix = self._sale_status_prefix(version)
        # resolve_target_path()가 붙이는 표준 문서명과 확장자까지 경로
        # 제한에 포함한다. 가장 긴 일반 확장자(hwpx)를 예약해 두어
        # 상품 폴더를 계산한 뒤 약관 파일에서 길이 제한을 넘지 않게 한다.
        max_document_filename = max(
            len(self._safe_component(label, max_length=40))
            for label in DocumentType.FOLDER_NAME.values()
        ) + len(".hwpx")
        if target is None:
            directory = company / "날짜미상"
            prefix = f"{state_prefix}날짜미상_"
            available = self.max_path_length - len(str(directory)) - len(prefix) - max_document_filename - 2
            product = self._fit_component(product, available)
            return directory / f"{prefix}{product}"

        year_month = company / f"{target:%Y}" / f"{target:%m}"
        prefix = f"{state_prefix}{target:%Y%m%d}_"
        available = self.max_path_length - len(str(year_month)) - len(prefix) - max_document_filename - 2
        product = self._fit_component(product, available)
        return year_month / f"{prefix}{product}"

    # ------------------------------------------------------------------
    # 파일명
    # ------------------------------------------------------------------
    @staticmethod
    def _sale_status_prefix(version: ProductVersion) -> str:
        """상품 폴더 전용 상태 접두사(``판매중__`` 등)."""
        return status_prefix(version.normalized_sale_status)

    def build_filename(
        self,
        version: ProductVersion,
        document_type: str,
        extension: str,
        original_filename: str = "",
    ) -> str:
        """문서유형과 실제 확장자만 사용하는 짧은 파일명."""
        del version
        doc_label = DocumentType.FOLDER_NAME.get(document_type, "미분류")
        stem = self._safe_component(doc_label, max_length=40)
        ext = normalize_extension(extension)
        if not ext:
            ext = split_extension(original_filename)[1]
        return stem + ext

    def resolve_target_path(
        self,
        version: ProductVersion,
        document_type: str,
        extension: str,
        original_filename: str = "",
    ) -> tuple[Path, str]:
        """(전체 저장 경로, 파일명) 을 돌려준다."""
        ext = normalize_extension(extension)
        if not ext:
            ext = split_extension(original_filename)[1]

        directory = self.version_dir(version)
        filename = self.build_filename(version, document_type, ext, original_filename)
        path = directory / filename
        if len(str(path)) > self.max_path_length:
            get_logger().warning(
                "저장 경로가 길이 제한(%d)을 초과합니다: %s (%d자)",
                self.max_path_length, path, len(str(path)),
            )
        return path, filename

    # ------------------------------------------------------------------
    def next_available_path(self, path: Path) -> Path:
        """이미 있는 파일명을 피해 _2, _3 … 를 붙인 경로를 돌려준다.

        기존 파일은 절대 삭제/덮어쓰지 않는다.
        """
        if not retry_file_operation(
            lambda: strict_exists(path) if self.is_network_output else path.exists(),
            path=path,
            operation_name="충돌 파일 대상 확인",
        ):
            return path
        stem, ext = split_extension(path.name)
        index = 2
        while True:
            candidate = path.with_name(f"{stem}_{index}{ext}")
            if not retry_file_operation(
                lambda: strict_exists(candidate)
                if self.is_network_output
                else candidate.exists(),
                path=candidate,
                operation_name="충돌 파일 후보 확인",
            ):
                return candidate
            index += 1

    # ------------------------------------------------------------------
    # 이름 정규화. ``normalize_storage_component``의 길이 초과 해시를 사용하지 않는다.
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_component(value: str, max_length: int = 120) -> str:
        # 큰 max_length로 먼저 정규화해 shorten()의 해시 접미사를 피한다.
        text = normalize_storage_component(value or "_", max_length=10_000)
        return PathService._fit_component(text, max_length)

    @staticmethod
    def _fit_component(value: str, max_length: int) -> str:
        limit = max(1, int(max_length))
        if len(value) <= limit:
            return value
        # 상품명은 파일명에 식별자를 추가하지 않기로 했으므로 단순 절단한다.
        return value[:limit].rstrip(" .") or "_"
