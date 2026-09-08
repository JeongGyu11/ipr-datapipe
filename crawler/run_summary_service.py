"""실행 summary JSON 저장기.

문서 상태 정본과 실행 요약을 분리한다. 이 모듈은 manifest 이름이나
전역 수집목록 경로를 참조하지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

from utils.network_io import durable_write_bytes, retry_file_operation, safe_unlink


SUMMARY_LAYOUT_VERSION = 3


class RunSummaryWriter:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(self, summary: dict) -> None:
        if not isinstance(summary, dict):
            raise ValueError("summary는 객체여야 합니다")
        summary = dict(summary)
        supplied = summary.get("layout_version", SUMMARY_LAYOUT_VERSION)
        if int(supplied) != SUMMARY_LAYOUT_VERSION:
            raise ValueError(f"지원하지 않는 summary layout_version: {supplied!r}")
        summary["layout_version"] = SUMMARY_LAYOUT_VERSION
        text = json.dumps(summary, ensure_ascii=False, indent=1)
        json.loads(text)
        retry_file_operation(
            lambda: self.path.parent.mkdir(parents=True, exist_ok=True),
            path=self.path.parent,
            operation_name="summary 디렉터리 생성",
        )
        temp = self.path.with_name(f"{self.path.name}.tmp")
        try:
            durable_write_bytes(temp, text.encode("utf-8"))
            retry_file_operation(
                lambda: temp.replace(self.path),
                path=self.path,
                operation_name="summary 원자 교체",
            )
        finally:
            try:
                safe_unlink(temp)
            except OSError:
                pass
