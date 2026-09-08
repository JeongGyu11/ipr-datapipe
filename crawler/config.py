"""실행 설정(config.yaml)과 보험사 Python catalog 로딩."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """중첩 mapping만 병합하고 list/scalar는 override 값으로 교체한다."""

    merged = dict(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_config_data(path: Path, seen: frozenset[Path] = frozenset()) -> dict[str, Any]:
    """선택적 ``extends``를 따라 컨테이너용 overlay 설정을 읽는다."""

    resolved = path.resolve()
    if resolved in seen:
        raise ValueError(f"설정 extends 순환 참조입니다: {resolved}")
    if not resolved.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {resolved}")
    with open(resolved, encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    if not isinstance(data, dict):
        raise ValueError(f"설정 최상위 값은 mapping이어야 합니다: {resolved}")

    parent = data.pop("extends", None)
    if not parent:
        return data
    parent_path = Path(str(parent))
    if not parent_path.is_absolute():
        parent_path = resolved.parent / parent_path
    base = _load_config_data(parent_path, seen | {resolved})
    return _merge_config(base, data)


@dataclass
class AppConfig:
    target_month: str | None
    base_path: str
    root_folder: str
    crawler: dict[str, Any]
    download: dict[str, Any]
    document_types: dict[str, list[str]]
    document_exclude_keywords: list[str]
    date_selection_mode: str
    # 컨테이너에서 SMB bind mount가 /data로 보이는 경우에도
    # Windows UNC와 Linux SMB bind mount에 같은 재시도/내구화 정책을 적용한다.
    storage_kind: str = "auto"
    local_staging_path: str | None = None
    local_state_path: str | None = None

    # --- crawler 편의 접근자 -------------------------------------------------
    @property
    def request_interval(self) -> float:
        return float(self.crawler.get("request_interval_seconds", 2))

    @property
    def timeout(self) -> float:
        return float(self.crawler.get("request_timeout_seconds", 30))

    @property
    def max_retries(self) -> int:
        return int(self.crawler.get("max_retries", 3))

    @property
    def retry_backoff(self) -> list[float]:
        return [float(x) for x in self.crawler.get("retry_backoff_seconds", [3, 10, 30])]

    @property
    def retry_status_codes(self) -> set[int]:
        return {int(x) for x in self.crawler.get("retry_status_codes", [408, 429, 500, 502, 503, 504])}

    @property
    def headless(self) -> bool:
        return bool(self.crawler.get("headless", True))

    @property
    def user_agent(self) -> str:
        return self.crawler.get("user_agent") or "Mozilla/5.0"

    @property
    def allowed_extensions(self) -> set[str]:
        return {str(x).lower() for x in self.download.get("allowed_extensions", [".pdf"])}

    @property
    def allowed_content_types(self) -> set[str]:
        return {str(x).lower() for x in self.download.get("allowed_content_types", ["application/pdf"])}

    @property
    def max_path_length(self) -> int:
        return int(self.download.get("max_path_length", 240))

def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    data = _load_config_data(path)

    output = data.get("output") or {}
    # 출력 경로와 저장소 모드는 설정 파일을 단일 정본으로 사용한다.
    base_path = output.get("base_path", "")
    storage_kind = str(output.get("storage_kind", "auto") or "auto").strip().lower()
    if storage_kind not in {"auto", "local", "smb"}:
        raise ValueError(f"지원하지 않는 저장소 모드입니다: {storage_kind}")
    local_staging_path = output.get("local_staging_path")
    local_state_path = output.get("local_state_path")
    raw_target_month = data.get("target_month")
    target_month = str(raw_target_month).strip() if raw_target_month is not None else None
    return AppConfig(
        target_month=target_month or None,
        base_path=str(base_path),
        root_folder=str(output.get("root_folder", "상품공시실문서")),
        crawler=dict(data.get("crawler") or {}),
        download=dict(data.get("download") or {}),
        document_types={k: list(v) for k, v in (data.get("document_types") or {}).items()},
        document_exclude_keywords=list(data.get("document_exclude_keywords") or []),
        date_selection_mode=str((data.get("date_selection") or {}).get("mode", "new_or_revised")),
        storage_kind=str(storage_kind or "auto"),
        local_staging_path=(str(local_staging_path) if local_staging_path else None),
        local_state_path=(str(local_state_path) if local_state_path else None),
    )
