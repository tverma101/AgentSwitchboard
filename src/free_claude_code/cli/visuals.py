"""Local terminal visual UX and focused-window Appshot capture."""

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from free_claude_code.core.visual_attachments import (
    VisualAttachmentReceipt,
    validate_image_bytes,
)

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_DEFAULT_APPSHOT_QUEUE = Path.home() / ".fcc" / "appshots"


def terminal_image_protocol(env: dict[str, str] | None = None) -> str | None:
    """Return a supported inline-image protocol, or None for text fallback."""
    values = os.environ if env is None else env
    if values.get("TMUX") or values.get("STY"):
        return None
    if values.get("TERM_PROGRAM") == "iTerm.app":
        return "iterm2"
    if values.get("KITTY_WINDOW_ID"):
        return "kitty"
    if values.get("TERM", "").lower().startswith("xterm-kitty"):
        return "kitty"
    if values.get("SIXEL_SUPPORT") == "1" or "sixel" in values.get("TERM", "").lower():
        return "sixel"
    return None


def render_attachment_card(data: bytes, *, media_type: str, label: str) -> str:
    """Produce the safe fallback card used when inline graphics are unavailable."""
    return validate_image_bytes(data, media_type=media_type, label=label).card()


def render_attachment(
    data: bytes,
    *,
    media_type: str,
    label: str,
    env: dict[str, str] | None = None,
) -> str:
    """Render one local attachment with a protocol preview or compact fallback."""
    receipt = validate_image_bytes(data, media_type=media_type, label=label)
    protocol = terminal_image_protocol(env)
    if protocol == "iterm2":
        return f"{_iterm2_image(data, media_type=media_type)}\n{receipt.card()}"
    if protocol == "kitty":
        return f"{_kitty_image(data)}\n{receipt.card()}"
    # Sixel support is detected for telemetry, but encoding is intentionally not
    # bundled: emitting a guessed sixel stream is worse than a truthful card.
    return receipt.card()


def _iterm2_image(data: bytes, *, media_type: str) -> str:
    import base64

    encoded = base64.b64encode(data).decode("ascii")
    return (
        "\x1b]1337;File="
        "inline=1;preserveAspectRatio=1;"
        f"size={len(data)};type={media_type}:{encoded}\x07"
    )


def _kitty_image(data: bytes) -> str:
    import base64

    encoded = base64.b64encode(data).decode("ascii")
    chunks = [encoded[index : index + 4096] for index in range(0, len(encoded), 4096)]
    return "".join(
        f"\x1b_Ga=T,f=100,t=d,m={int(index < len(chunks) - 1)};{chunk}\x1b\\"
        for index, chunk in enumerate(chunks)
    )


def capture_focused_window(output_dir: Path) -> Path:
    """Capture only the focused macOS window using the system screenshot tool."""
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "appshot.png"
    # ``-w`` asks macOS to capture a window; the OS permission/selection UI is
    # deliberately retained rather than simulating a click into another app.
    result = subprocess.run(
        ["screencapture", "-w", "-o", "-x", str(destination)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not destination.is_file():
        raise RuntimeError(
            "Focused-window capture failed; grant Screen Recording access"
        )
    return destination


def focused_window_metadata() -> dict[str, str]:
    """Read the frontmost app and window title through Accessibility metadata."""
    script = (
        'tell application "System Events" to tell first process whose frontmost is true '
        'to return name & linefeed & (value of attribute "AXTitle" of front window)'
    )
    result = subprocess.run(
        ["osascript", "-e", script], check=True, text=True, capture_output=True
    )
    parts = result.stdout.splitlines()
    app = parts[0].strip() if parts else "Unknown app"
    title = parts[1].strip() if len(parts) > 1 else ""
    return {"app": app, "window": title}


def write_appshot_receipt(path: Path, *, metadata: dict[str, Any]) -> Path:
    """Write a local queue receipt consumed by a wrapper/session integration."""
    receipt = path.with_suffix(".json")
    receipt.write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


@dataclass(frozen=True, slots=True)
class AppshotAttachment:
    """Local Appshot metadata queued for one explicitly named Claude session."""

    session_id: str
    image_path: Path
    visual: VisualAttachmentReceipt
    app: str
    window: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "image_path": str(self.image_path),
            "app": self.app,
            "window": self.window,
            "visual": self.visual.as_dict(),
        }

    def confirmation(self) -> str:
        title = f"{self.app} — {self.window}" if self.window else self.app
        return f"[appshot: {title} · {self.visual.width}\u00d7{self.visual.height}]"


def build_appshot_attachment(
    image_path: Path,
    *,
    session_id: str,
    metadata: dict[str, str],
) -> AppshotAttachment:
    """Validate a captured image and bind it to an explicit session id."""
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError("session_id must be a short opaque identifier")
    data = image_path.read_bytes()
    visual = validate_image_bytes(data, media_type="image/png", label="appshot")
    return AppshotAttachment(
        session_id=session_id,
        image_path=image_path,
        visual=visual,
        app=metadata.get("app", "Unknown app"),
        window=metadata.get("window", ""),
    )


def appshot_queue_dir(root: Path | None = None) -> Path:
    """Return the local, demand-only Appshot queue directory."""
    if root is not None:
        return root
    configured = os.environ.get("FCC_APPSHOT_QUEUE")
    return Path(configured).expanduser() if configured else _DEFAULT_APPSHOT_QUEUE


def enqueue_appshot(attachment: AppshotAttachment, *, root: Path | None = None) -> Path:
    """Persist metadata for a wrapper/session consumer without storing image bytes."""
    queue = appshot_queue_dir(root)
    queue.mkdir(parents=True, exist_ok=True)
    destination = (
        queue / f"{attachment.session_id}-{attachment.visual.attachment_id}.json"
    )
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(attachment.as_dict(), sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(destination)
    return destination


def pending_appshots(session_id: str, *, root: Path | None = None) -> tuple[Path, ...]:
    """List only the queued receipts for one explicit session."""
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError("session_id must be a short opaque identifier")
    queue = appshot_queue_dir(root)
    return tuple(sorted(queue.glob(f"{session_id}-*.json")))


def capture_and_enqueue_appshot(
    *, session_id: str, root: Path | None = None
) -> tuple[AppshotAttachment, Path]:
    """Capture the focused window and enqueue it for one named session."""
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError("session_id must be a short opaque identifier")
    queue = appshot_queue_dir(root)
    queue.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="fcc-appshot-", dir=queue))
    try:
        image_path = capture_focused_window(work_dir)
        metadata = focused_window_metadata()
        attachment = build_appshot_attachment(
            image_path,
            session_id=session_id,
            metadata=metadata,
        )
        session_dir = queue / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        final_path = session_dir / f"{attachment.visual.attachment_id}.png"
        if final_path.exists():
            image_path.unlink()
        else:
            image_path.replace(final_path)
        persisted = AppshotAttachment(
            session_id=attachment.session_id,
            image_path=final_path,
            visual=attachment.visual,
            app=attachment.app,
            window=attachment.window,
        )
        receipt = enqueue_appshot(persisted, root=queue)
        return persisted, receipt
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def appshot_temp_dir() -> tempfile.TemporaryDirectory[str]:
    """Create a demand-only Appshot directory; callers own its cleanup."""
    return tempfile.TemporaryDirectory(prefix="fcc-appshot-")
