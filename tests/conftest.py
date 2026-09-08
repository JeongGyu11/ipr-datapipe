import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from crawler.config import load_config  # noqa: E402
from crawler.validators import DocumentClassifier  # noqa: E402
from utils.network_io import reset_network_path  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_network_path_registry():
    reset_network_path()
    yield
    reset_network_path()


def pytest_addoption(parser):
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="실제 보험사 사이트를 호출하는 통합 테스트를 실행합니다.",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-network"):
        return
    skip = pytest.mark.skip(reason="네트워크 통합 테스트: --run-network 로 실행하세요")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def config():
    return load_config(ROOT / "config.yaml")


@pytest.fixture(scope="session")
def classifier(config):
    return DocumentClassifier(config.document_types, config.document_exclude_keywords)
