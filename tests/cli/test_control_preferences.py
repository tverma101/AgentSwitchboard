from pathlib import Path

from free_claude_code.cli.control_preferences import (
    DEFAULT_THEME,
    load_theme,
    save_theme,
)


def test_load_theme_returns_default_for_missing_or_invalid_preferences(
    tmp_path: Path,
) -> None:
    path = tmp_path / "control-center.json"

    assert load_theme(path) == DEFAULT_THEME

    path.write_text("not-json", encoding="utf-8")
    assert load_theme(path) == DEFAULT_THEME

    path.write_text("[]", encoding="utf-8")
    assert load_theme(path) == DEFAULT_THEME

    path.write_text('{"theme": "  "}', encoding="utf-8")
    assert load_theme(path) == DEFAULT_THEME


def test_save_theme_round_trips_and_replaces_atomically(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "control-center.json"

    save_theme("  nord  ", path)
    assert load_theme(path) == "nord"

    save_theme("gruvbox", path)
    assert load_theme(path) == "gruvbox"
    assert path.read_text(encoding="utf-8") == '{\n  "theme": "gruvbox"\n}\n'
