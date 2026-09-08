"""Linux container SMB mount compatibility tests."""

from pathlib import Path

import pytest

import scripts.smoke_test_storage as smoke_test_storage
import utils.network_io as network_io
from crawler.config import load_config
from crawler.path_service import PathService


def test_linux_smb_mount_uses_network_semantics_and_overrides(tmp_path):
    service = PathService(
        base_path="/data",
        root_folder="상품공시실문서",
        target_month="2026-07",
        storage_kind="smb",
        local_staging_override=tmp_path / "staging",
        local_state_override=tmp_path / "state",
    )

    assert service.is_network_output is True
    assert service.output_root == Path("/data/상품공시실문서")
    assert service.local_staging_root == tmp_path / "staging"
    assert service.local_state_root == tmp_path / "state"
    assert network_io.is_network_path("/data/상품공시실문서/99_운영/locks/MERITZ.lock")
    assert not network_io.is_network_path(tmp_path / "staging" / "download.pdf")


def test_network_path_prefix_requires_explicit_registration(monkeypatch):
    network_io.configure_network_path("/mnt/insurance-output")
    assert network_io.is_network_path("/mnt/insurance-output/상품공시실문서/01_문서")
    assert not network_io.is_network_path("/mnt/insurance-output-test/file.pdf")
    assert not network_io.is_network_path("/tmp/file.pdf")


def test_environment_does_not_override_config_storage(monkeypatch, tmp_path):
    config_path = Path(__file__).resolve().parents[1] / "config.yaml"
    monkeypatch.setenv("CRAWLER_OUTPUT_BASE_PATH", "/data")
    monkeypatch.setenv("CRAWLER_STORAGE_KIND", "smb")
    monkeypatch.setenv("CRAWLER_LOCAL_STAGING_PATH", str(tmp_path / "staging"))
    monkeypatch.setenv("CRAWLER_LOCAL_STATE_PATH", str(tmp_path / "state"))

    config = load_config(config_path)

    assert config.base_path != "/data"
    assert config.storage_kind != "smb"


def test_container_config_extends_base_without_copying_companies(monkeypatch):
    project_root = Path(__file__).resolve().parents[1]
    monkeypatch.delenv("CRAWLER_OUTPUT_BASE_PATH", raising=False)
    monkeypatch.delenv("CRAWLER_STORAGE_KIND", raising=False)
    monkeypatch.delenv("CRAWLER_LOCAL_STAGING_PATH", raising=False)
    monkeypatch.delenv("CRAWLER_LOCAL_STATE_PATH", raising=False)

    base = load_config(project_root / "config.yaml")
    container = load_config(project_root / "config.container.yaml")

    assert container.base_path == "/data"
    assert container.root_folder == "상품공시실문서"
    assert container.storage_kind == "smb"
    assert container.local_state_path == "/var/lib/insurance-document-crawler/state"
    assert container.local_staging_path == "/var/lib/insurance-document-crawler/staging"
    assert base.base_path != container.base_path


def test_smoke_cleanup_does_not_mask_original_validation_error(tmp_path, monkeypatch):
    artifact = tmp_path / "artifact.tmp"
    artifact.write_bytes(b"leftover")

    def failing_unlink(_path):
        raise OSError("cleanup failed")

    monkeypatch.setattr(smoke_test_storage, "safe_unlink", failing_unlink)

    with pytest.raises(ValueError, match="primary validation failed"):
        try:
            raise ValueError("primary validation failed")
        finally:
            smoke_test_storage._cleanup_smoke_artifacts(
                (artifact,),
                tmp_path / "still-not-empty",
                tmp_path,
                suppress_errors=True,
            )
