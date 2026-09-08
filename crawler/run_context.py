"""실행 식별자와 프로세스 실행 정보를 한 곳에서 관리한다.

개인 식별자(예: ``CRAWLER_OPERATOR``)는 런타임 감사 정보에 포함하지
않는다.  ``RunContext``는 재현·장애 조사에 필요한 프로세스 수준 식별자만
보유한다. 과거 lock JSON에 ``operator``가 남아 있더라도 lock reader가
무시할 수 있도록 이 타입 자체는 해당 키를 생성하지 않는다.
"""

from __future__ import annotations

import os
import platform
import subprocess
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

@dataclass(frozen=True)
class RunContext:
    run_id: str
    computer_name: str
    process_id: int
    started_at: str
    git_commit: str = ""

    @classmethod
    def create(cls, project_root: Path | None = None) -> "RunContext":
        return cls(
            run_id=f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}",
            computer_name=platform.node() or os.environ.get("COMPUTERNAME", ""),
            process_id=os.getpid(),
            started_at=datetime.now().isoformat(timespec="seconds"),
            git_commit=_git_commit(project_root),
        )

    def to_dict(self) -> dict:
        return asdict(self)


def _git_commit(project_root: Path | None) -> str:
    if project_root is None:
        return ""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()
