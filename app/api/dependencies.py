"""FastAPI API에서 사용하는 런타임 설정과 출력 경로 의존성."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException
from yaml import YAMLError

from app.config_paths import resolve_config_path
from crawler.config import AppConfig, load_config
from crawler.path_service import PathService


def config_file_path() -> Path:
    """API 프로세스가 사용할 config.yaml 경로를 반환한다.

    컨테이너에서는 ``/app``을 기준으로 찾고, 테스트/운영에서는
    ``CRAWLER_CONFIG_PATH``로 명시적으로 교체할 수 있다.
    """

    return resolve_config_path()


def get_app_config() -> AppConfig:
    """프로젝트와 동일한 config/env 해석 규칙으로 설정을 읽는다."""

    try:
        return load_config(config_file_path())
    except (FileNotFoundError, OSError, ValueError, YAMLError) as exc:
        raise HTTPException(status_code=503, detail=f"crawler configuration is unavailable: {exc}") from exc


def get_path_service(config: Annotated[AppConfig, Depends(get_app_config)]) -> PathService:
    """실행 summary가 저장되는 기존 ``99_운영/runs`` 경로를 반환한다."""

    scope_key = config.target_month or "config"
    return PathService(
        base_path=config.base_path,
        root_folder=config.root_folder,
        target_month=scope_key,
        max_path_length=config.max_path_length,
        scope_key=scope_key,
        storage_kind=config.storage_kind,
        local_staging_override=config.local_staging_path,
        local_state_override=config.local_state_path,
    )


PathServiceDependency = Annotated[PathService, Depends(get_path_service)]
