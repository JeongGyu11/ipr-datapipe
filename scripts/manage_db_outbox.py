"""DB outbox를 payload 노출 없이 점검하고 수동 승인으로 격리한다."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from crawler.db_outbox import DatabaseOutbox


def _failure_counts(path: Path) -> dict[str, int]:
    counts: Counter[str] = Counter()
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            if not line.strip():
                continue
            payload = json.loads(line)
            counts[str(payload.get("failure_kind") or "UNKNOWN")] += 1
    return dict(sorted(counts.items()))


def inspect_outbox(outbox: DatabaseOutbox) -> dict:
    pending = outbox.pending()
    events = []
    for envelope in pending:
        event = envelope.get("event") or {}
        payload = event.get("payload")
        rows = payload if isinstance(payload, list) else [payload]
        document_keys = [
            str(row.get("document_key") or "")
            for row in rows
            if isinstance(row, dict) and row.get("document_key")
        ]
        events.append(
            {
                "event_id": envelope.get("event_id"),
                "created_at": envelope.get("created_at"),
                "operation": event.get("operation"),
                "row_count": len(rows) if rows != [None] else 0,
                "document_key_prefixes": [key[:12] for key in document_keys[:10]],
            }
        )
    return {
        "path": str(outbox.path.resolve()),
        "pending_count": len(events),
        "failure_counts": _failure_counts(outbox.failure_path),
        "events": events,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, type=Path, help="보험사 DB outbox JSONL")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inspect", help="payload 본문 없이 대기 이벤트를 조회")
    quarantine = subparsers.add_parser("quarantine", help="수동 승인된 이벤트를 격리")
    quarantine.add_argument("--event-id", required=True)
    quarantine.add_argument("--reason", required=True)
    quarantine.add_argument(
        "--approval-id",
        required=True,
        help="사람 이름 대신 run_id@computer:pid 형식의 비인격 감사 식별자",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    outbox = DatabaseOutbox(args.path)
    if args.command == "quarantine":
        outbox.quarantine(
            args.event_id,
            reason=args.reason,
            approved_by=args.approval_id,
        )
    print(json.dumps(inspect_outbox(outbox), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
