"""수집과 PDF Load CLI를 분기하는 얇은 실행 진입점."""

from __future__ import annotations

import sys

from app.cli import main as collection_main


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if values and values[0] == "load":
        from app.load_cli import main as load_main

        return load_main(values[1:])
    return collection_main(values)


if __name__ == "__main__":
    raise SystemExit(main())
