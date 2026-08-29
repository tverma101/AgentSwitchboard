"""Small, non-secret preferences for the terminal control center."""

import json
import os
from pathlib import Path

from free_claude_code.config.paths import control_center_preferences_path

DEFAULT_THEME = "harlequin"


def load_theme(path: Path | None = None) -> str:
    """Return the saved theme name, or the control center default."""

    preference_path = control_center_preferences_path() if path is None else path
    try:
        payload = json.loads(preference_path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError, TypeError:
        return DEFAULT_THEME
    if not isinstance(payload, dict):
        return DEFAULT_THEME
    theme = payload.get("theme")
    return theme.strip() if isinstance(theme, str) and theme.strip() else DEFAULT_THEME


def save_theme(theme: str, path: Path | None = None) -> None:
    """Persist one non-secret theme preference with an atomic replacement."""

    theme = theme.strip()
    if not theme:
        raise ValueError("theme name cannot be empty")
    preference_path = control_center_preferences_path() if path is None else path
    preference_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = preference_path.with_suffix(f"{preference_path.suffix}.tmp")
    temporary.write_text(
        json.dumps({"theme": theme}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, preference_path)
