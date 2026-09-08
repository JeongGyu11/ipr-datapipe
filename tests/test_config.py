from pathlib import Path

from crawler.config import load_config


def test_load_config_normalizes_nullable_target_month(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("target_month: ' 2026-08 '\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.target_month == "2026-08"


def test_load_config_preserves_missing_or_null_target_month_as_none(tmp_path: Path) -> None:
    null_path = tmp_path / "null.yaml"
    null_path.write_text("target_month: null\n", encoding="utf-8")
    missing_path = tmp_path / "missing.yaml"
    missing_path.write_text("output: {}\n", encoding="utf-8")

    assert load_config(null_path).target_month is None
    assert load_config(missing_path).target_month is None


def test_repository_config_has_no_fixed_target_month() -> None:
    project_root = Path(__file__).resolve().parents[1]

    assert load_config(project_root / "config.yaml").target_month is None
