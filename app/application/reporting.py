"""Human-readable logging for completed collection runs."""

from __future__ import annotations

import json
from typing import Any

from utils.crawler_logger import get_logger


def log_summary(summary: dict[str, Any], logger=None) -> None:
    """Emit the existing one-record multiline collection summary."""

    logger = logger or get_logger()
    lines = ["", "=" * 72]
    lines.append(f"실행 ID       : {summary['run_id']}")
    lines.append(
        f"PC/PID        : {summary.get('computer_name', '')} / "
        f"{summary.get('process_id', '')}"
    )
    lines.append(
        f"시작/commit    : {summary.get('started_at', '')} / "
        f"{summary.get('git_commit', '')}"
    )
    label = summary.get("target_month") or summary.get("scope_key") or "알 수 없음"
    lines.append(
        f"수집 범위     : {label} "
        f"({summary['period']['start']} ~ {summary['period']['end']})"
    )
    lines.append(f"선정 방식     : {summary['date_selection_mode']}")
    lines.append(f"소요 시간     : {summary['elapsed_seconds']}초")
    artifact_paths = summary.get("artifact_paths") or {}
    lines.append(f"저장 루트     : {artifact_paths.get('documents', '')}")
    lines.append("-" * 72)
    for code, info in (summary.get("companies") or {}).items():
        lines.append(f"[{code}] {info.get('name', '')}")
        lines.append(f"    수집 방식      : {info.get('collection_method', '')}")
        if info.get("error"):
            lines.append(f"    오류           : {info['error']}")
            continue
        if info.get("download_plan"):
            lines.append(f"    다운로드 plan  : {info['download_plan']}")
            lines.append(
                f"    계획/남은 문서 : {info.get('planned_documents', 0)} / "
                f"{info.get('remaining_documents', 0)}"
            )
        lines.append(f"    대상 상품 수   : {info.get('products', 0)}")
        lines.append(
            f"    대상 버전 수   : {info.get('selected_versions', 0)} / "
            f"전체 수집 {info.get('collected_versions', 0)}"
        )
        lines.append(f"    문서 링크 수   : {info.get('document_links', 0)}")
        lines.append(
            f"    상태           : "
            f"{json.dumps(info.get('status_counts', {}), ensure_ascii=False)}"
        )
        lines.append(
            f"    누락 문서      : "
            f"{json.dumps(info.get('missing_documents', {}), ensure_ascii=False)}"
        )
        if info.get("coverage_capped"):
            if info.get("products_total"):
                lines.append(
                    f"    ** 범위 제한   : 등록 상품 약 {info.get('products_total')}개 중 "
                    f"{info.get('products_skipped')}개 미조회 (coverage_capped) **"
                )
            if info.get("versions_total"):
                lines.append(
                    f"    ** 범위 제한   : 대상 버전 {info.get('versions_total')}건 중 "
                    f"{info.get('versions_skipped')}건 미처리 (coverage_capped) **"
                )
        for path in info.get("sample_paths", [])[:3]:
            lines.append(f"    예상 저장 경로 : {path}")
    lines.append("-" * 72)
    lines.append(
        f"전체 상태     : "
        f"{json.dumps(summary.get('status_counts', {}), ensure_ascii=False)}"
    )
    lines.append("=" * 72)
    logger.info("%s", "\n".join(lines))
