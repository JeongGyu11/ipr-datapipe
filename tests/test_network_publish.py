"""네트워크 출력 publish 분기의 로컬 재현 테스트.

실제 파일 서버를 요구하지 않도록 출력/임시 경로는 tmp_path에 두고,
PathService의 네트워크 출력 분기만 강제로 선택한다.
"""

import builtins
import errno
from pathlib import Path

import crawler.download_service as download_module
from crawler.config import load_config
from crawler.download_service import DownloadService
from crawler.manifest_service import ManifestService
from crawler.path_service import PathService
from crawler.validators import ValidationResult
from models.document import DocumentType
from utils.crawler_logger import ErrorRecorder, setup_logging
from utils.hash_utils import sha256_bytes

from tests.test_download_staging import PDF, make_version


ROOT = Path(__file__).resolve().parents[1]


class LocalNetworkPathService(PathService):
    def __init__(self, tmp_path: Path):
        super().__init__(
            base_path=str(tmp_path / "output"),
            root_folder="상품공시실문서",
            target_month="2026-07",
        )
        self._local_root = tmp_path / "local-staging"
        self._server_root = tmp_path / "server-staging"

    @property
    def is_network_output(self) -> bool:
        return True

    def download_staging_dir(self, run_id: str, company_code: str) -> Path:
        return self._local_root / run_id / company_code

    def server_upload_staging_dir(self, run_id: str, company_code: str) -> Path:
        return self._server_root / run_id / company_code


def make_network_service(tmp_path: Path):
    setup_logging(None)
    config = load_config(ROOT / "config.yaml")
    paths = LocalNetworkPathService(tmp_path)
    manifest = ManifestService(
        output_root=paths.output_root,
        run_id="RUN-NETWORK",
    )
    service = DownloadService(
        config=config,
        paths=paths,
        manifest=manifest,
        errors=ErrorRecorder(None),
    )
    version = make_version()
    target, _ = paths.resolve_target_path(version, DocumentType.POLICY, ".pdf", "원본_약관.pdf")
    return service, paths, version, target


def publish(service, paths, target, content=PDF):
    return service._publish_validated_file(
        content=content,
        target=target,
        extension=".pdf",
        digest=sha256_bytes(content),
        run_id="RUN-NETWORK",
        company_code="DB",
    )


def test_network_publish_copies_and_cleans_both_temporary_files(tmp_path):
    service, paths, _, target = make_network_service(tmp_path)

    published = publish(service, paths, target)

    assert published.read_bytes() == PDF
    assert not list(paths.download_staging_dir("RUN-NETWORK", "DB").rglob("*"))
    assert not list(paths.server_upload_staging_dir("RUN-NETWORK", "DB").rglob("*"))


def test_network_publish_retries_transient_server_copy_open(tmp_path, monkeypatch):
    service, paths, _, target = make_network_service(tmp_path)
    original_open = builtins.open
    attempts = 0

    def flaky_open(path, mode="r", *args, **kwargs):
        nonlocal attempts
        if Path(path).name.startswith(".upload_") and "xb" in mode:
            attempts += 1
            if attempts == 1:
                raise OSError(errno.EINVAL, "temporary server error")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", flaky_open)
    real_retry = download_module.retry_file_operation

    def force_retry(operation, **kwargs):
        # Windows UNC 대상에서만 발생하는 일시 오류 재시도 경로를
        # 로컬 테스트에서도 검증하기 위해 의도적으로 UNC 문자열을 주입한다.
        kwargs["path"] = r"\\Fileserver\share\upload"
        kwargs["backoff"] = ()
        return real_retry(operation, **kwargs)

    monkeypatch.setattr(download_module, "retry_file_operation", force_retry)
    published = publish(service, paths, target)

    assert published.read_bytes() == PDF
    assert attempts == 2


def test_network_publish_removes_new_target_when_final_validation_fails(tmp_path, monkeypatch):
    service, paths, _, target = make_network_service(tmp_path)
    real_validate = download_module.validate_saved_file

    def fail_target(path, expected_size, extension):
        if Path(path) == target:
            return ValidationResult(False, "INVALID_FILE", "최종 검증 실패")
        return real_validate(path, expected_size, extension)

    monkeypatch.setattr(download_module, "validate_saved_file", fail_target)
    try:
        publish(service, paths, target)
    except OSError as exc:
        assert "검증 실패" in str(exc)
    else:
        raise AssertionError("최종 검증 실패가 전파되어야 합니다")

    assert not target.exists()
    assert not list(paths.server_upload_staging_dir("RUN-NETWORK", "DB").rglob("*"))


def test_network_publish_does_not_overwrite_existing_target(tmp_path):
    service, paths, _, target = make_network_service(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((Path(ROOT) / "tests" / "fixtures" / "sample.pdf").read_bytes() + b"old")

    published = publish(service, paths, target)

    assert target.read_bytes().endswith(b"old")
    assert published != target
    assert published.read_bytes() == PDF
