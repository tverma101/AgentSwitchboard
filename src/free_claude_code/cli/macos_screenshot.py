"""Minimal macOS screenshot boundary adapted from Codex's screenshot helper."""

import json
import os
import subprocess
import tempfile
from collections.abc import Mapping
from functools import cache
from pathlib import Path

_VENDOR_DIR = Path(__file__).resolve().parent / "_vendor" / "openai_screenshot"
_PERMISSION_SCRIPT = _VENDOR_DIR / "macos_permissions.swift"
_WINDOW_SCRIPT = _VENDOR_DIR / "macos_focused_window.swift"

_TERM_PROGRAM_NAMES = {
    "Apple_Terminal": "Terminal",
    "iTerm.app": "iTerm",
    "vscode": "Visual Studio Code",
    "WarpTerminal": "Warp",
    "WezTerm": "WezTerm",
    "ghostty": "Ghostty",
}


class MacOSScreenRecordingPermissionError(RuntimeError):
    """macOS denied the Screen Recording permission needed for capture."""


def _swift_json(script: Path, *args: str) -> dict[str, object]:
    """Run one bundled Swift helper and return its JSON object."""
    module_cache = Path(tempfile.gettempdir()) / "fcc-swift-module-cache"
    module_cache.mkdir(parents=True, exist_ok=True)
    command = [
        "swift",
        "-module-cache-path",
        str(module_cache),
        str(script),
        *args,
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Swift is required for macOS screenshot permission/window lookup"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("macOS screenshot helper timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(detail or "macOS screenshot helper failed") from exc
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("macOS screenshot helper returned invalid JSON") from exc
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) for key in payload
    ):
        raise RuntimeError("macOS screenshot helper returned a non-object")
    return {key: value for key, value in payload.items() if isinstance(key, str)}


def screen_recording_granted() -> bool:
    """Return whether macOS currently grants Screen Recording access."""
    return _swift_json(_PERMISSION_SCRIPT).get("screenCapture") is True


@cache
def _request_screen_recording_once() -> None:
    """Ask macOS for Screen Recording at most once per FCC process."""
    _swift_json(_PERMISSION_SCRIPT, "--request")


def _screen_recording_host(env: Mapping[str, str]) -> str:
    term_program = env.get("TERM_PROGRAM", "").strip()
    if term_program:
        return _TERM_PROGRAM_NAMES.get(term_program, term_program)
    return "the terminal or app running FCC"


def _permission_message(env: Mapping[str, str]) -> str:
    host = _screen_recording_host(env)
    if host.startswith("the "):
        subject = host
        reopen = "that app"
    else:
        subject = host
        reopen = host
    return (
        f"Screen Recording permission is required for {subject}. "
        "Enable it in System Settings > Privacy & Security > "
        f"Screen & System Audio Recording, then quit and reopen {reopen} once."
    )


def ensure_screen_recording_permission(env: Mapping[str, str] | None = None) -> None:
    """Preflight Screen Recording and request it once without terminal prompt spam."""
    if screen_recording_granted():
        return
    _request_screen_recording_once()
    if screen_recording_granted():
        return
    raise MacOSScreenRecordingPermissionError(
        _permission_message(os.environ if env is None else env)
    )


def _required_int(value: object, *, name: str, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"focused window metadata has invalid {name}")
    if positive and value <= 0:
        raise RuntimeError(f"focused window metadata has invalid {name}")
    return value


def focused_window_metadata() -> dict[str, object]:
    """Return the exact frontmost Core Graphics window from the bundled helper."""
    payload = _swift_json(_WINDOW_SCRIPT)
    selected = payload.get("selected")
    if not isinstance(selected, dict):
        raise RuntimeError("no focused macOS window is available")

    bounds = selected.get("bounds")
    if not isinstance(bounds, dict):
        raise RuntimeError("focused window metadata is missing bounds")

    app = selected.get("owner")
    window = selected.get("name")
    bundle_id = selected.get("bundle_id")
    metadata: dict[str, object] = {
        "app": app if isinstance(app, str) and app.strip() else "Unknown app",
        "window": window if isinstance(window, str) else "",
        "x": _required_int(bounds.get("x"), name="x"),
        "y": _required_int(bounds.get("y"), name="y"),
        "width": _required_int(bounds.get("width"), name="width", positive=True),
        "height": _required_int(bounds.get("height"), name="height", positive=True),
        "window_id": _required_int(selected.get("id"), name="window_id", positive=True),
    }
    if isinstance(bundle_id, str) and bundle_id.strip():
        metadata["bundle_id"] = bundle_id
    return metadata


def capture_focused_window(output_dir: Path, window_id: int) -> Path:
    """Capture one Core Graphics window id without interactive selection."""
    if isinstance(window_id, bool) or not isinstance(window_id, int) or window_id <= 0:
        raise ValueError("focused window id must be a positive integer")
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "appshot.png"
    try:
        result = subprocess.run(
            [
                "screencapture",
                "-x",
                "-l",
                str(window_id),
                str(destination),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("macOS screencapture command is unavailable") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("focused-window capture timed out") from exc
    if result.returncode != 0 or not destination.is_file():
        raise RuntimeError("focused-window capture failed")
    return destination


__all__ = [
    "MacOSScreenRecordingPermissionError",
    "capture_focused_window",
    "ensure_screen_recording_permission",
    "focused_window_metadata",
    "screen_recording_granted",
]
