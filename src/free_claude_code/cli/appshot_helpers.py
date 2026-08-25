"""Small terminal helpers for persisted Appshot receipts.

These helpers consume the provider-neutral core Appshot schema. They never
print or serialize resolved local asset paths; path disclosure only occurs on
an explicit clipboard-copy action.
"""

import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from free_claude_code.core.appshot import (
    AppshotContractError,
    AppshotReceipt,
    FileAppshotQueue,
)

from .visuals import appshot_queue_dir


def _file_queue(root: Path | None) -> FileAppshotQueue:
    queue_root = appshot_queue_dir(root)
    if queue_root is None:
        raise AppshotContractError(
            "Appshot persistence is disabled; supply an explicit queue"
        )
    return FileAppshotQueue(queue_root)


def _read_receipt(
    receipt: Path, *, root: Path | None
) -> tuple[FileAppshotQueue, AppshotReceipt]:
    queue = _file_queue(root)
    queue_root = queue.root.resolve()
    candidate = receipt if receipt.is_absolute() else queue_root / receipt
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(queue_root)
    except (OSError, ValueError) as exc:
        raise AppshotContractError(
            "Appshot receipt is outside the local queue"
        ) from exc
    if not resolved.is_file():
        raise AppshotContractError("Appshot receipt is unavailable")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AppshotContractError("Appshot receipt is unreadable") from exc
    if not isinstance(payload, Mapping):
        raise AppshotContractError("Appshot receipt is not an object")
    parsed = AppshotReceipt.from_dict(payload)
    if queue.receipt_path(parsed).resolve() != resolved:
        raise AppshotContractError("Appshot receipt name does not match its metadata")
    return queue, parsed


def inspect_appshot(receipt: Path, *, root: Path | None = None) -> str:
    """Return compact persisted metadata without revealing the asset path."""
    _queue, parsed = _read_receipt(receipt, root=root)
    title = " ".join(parsed.metadata.display_title.split())[:160]
    return f"{parsed.visual.card()} · {title or 'Unknown app'}"


def resolve_appshot_image(receipt: Path, *, root: Path | None = None) -> Path:
    """Resolve a persisted asset for an explicit local action."""
    queue, parsed = _read_receipt(receipt, root=root)
    image = queue.asset_path(parsed)
    try:
        resolved = image.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise AppshotContractError("Appshot image is unavailable") from exc
    if not resolved.is_file():
        raise AppshotContractError("Appshot image is unavailable")
    return resolved


def open_appshot(
    receipt: Path,
    *,
    root: Path | None = None,
    opener: Callable[[Path], None] | None = None,
) -> None:
    """Open one persisted image locally without returning or printing its path."""
    image = resolve_appshot_image(receipt, root=root)
    if opener is not None:
        opener(image)
        return
    if sys.platform == "darwin":
        command = ["open", "--", str(image)]
    elif sys.platform == "win32":
        command = ["explorer", str(image)]
    else:
        command = ["xdg-open", str(image)]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("Default viewer could not open the attachment")


def copy_appshot_path(
    receipt: Path,
    *,
    root: Path | None = None,
    copier: Callable[[Path], None] | None = None,
) -> None:
    """Copy the resolved path only after the user explicitly requests it."""
    image = resolve_appshot_image(receipt, root=root)
    if copier is not None:
        copier(image)
        return
    if sys.platform == "darwin":
        command = ["pbcopy"]
    elif shutil.which("wl-copy"):
        command = ["wl-copy"]
    elif shutil.which("xclip"):
        command = ["xclip", "-selection", "clipboard"]
    else:
        raise RuntimeError("No local clipboard path helper is available")
    subprocess.run(
        command,
        input=str(image),
        check=True,
        capture_output=True,
        text=True,
    )


__all__ = [
    "copy_appshot_path",
    "inspect_appshot",
    "open_appshot",
    "resolve_appshot_image",
]
