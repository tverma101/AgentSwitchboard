"""Local terminal visual UX and focused-window Appshot capture."""

import io
import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from PIL import Image

from free_claude_code.core.appshot import (
    AppshotAttachment,
    AppshotPolicy,
    AppshotQueuePort,
    AppshotReceipt,
    FileAppshotQueue,
    FocusedWindowCapturePort,
    FocusedWindowMetadata,
    InMemoryAppshotQueue,
    TerminalSessionAssociation,
    capture_appshot,
)
from free_claude_code.core.visual_attachments import (
    validate_image_bytes,
)

_PREVIEW_MAX_EDGE = 1024
_PREVIEW_MAX_BYTES = 512 * 1024


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


def render_terminal_preview(
    data: bytes,
    *,
    media_type: str,
    label: str,
    env: dict[str, str] | None = None,
) -> str:
    """Render a bounded local preview followed by the original metadata card.

    Preview bytes are produced only for terminal display and never enter a
    provider request or receipt. Unsupported terminals receive the same
    metadata-only card without escape sequences.
    """
    receipt = validate_image_bytes(data, media_type=media_type, label=label)
    protocol = terminal_image_protocol(env)
    if protocol is None:
        return receipt.card()
    preview_data, preview_type = _thumbnail_for_terminal(data, media_type=media_type)
    if protocol == "iterm2":
        rendered = _iterm2_image(preview_data, media_type=preview_type)
    elif protocol == "kitty":
        rendered = _kitty_image(preview_data)
    else:
        # Sixel detection is intentionally truthful but encoding is not bundled.
        return receipt.card()
    return f"{rendered}\n{receipt.card()}"


def _thumbnail_for_terminal(data: bytes, *, media_type: str) -> tuple[bytes, str]:
    """Return the original image when small, otherwise a bounded JPEG preview."""
    with Image.open(io.BytesIO(data)) as source:
        if len(data) <= _PREVIEW_MAX_BYTES and max(source.size) <= _PREVIEW_MAX_EDGE:
            return data, media_type
        image = source.convert("RGB")
        image.thumbnail(
            (_PREVIEW_MAX_EDGE, _PREVIEW_MAX_EDGE), Image.Resampling.LANCZOS
        )
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=80, optimize=True)
    return output.getvalue(), "image/jpeg"


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


class MacOSFocusedWindowCapture:
    """Small macOS adapter for the provider-neutral capture port.

    The system ``screencapture`` command still owns OS permission and window
    selection.  This adapter only binds the inspected metadata to the bytes,
    rejects a focus change during the operation, and returns bytes to the
    caller so the default queue can remain non-persistent.
    """

    def __init__(
        self,
        *,
        metadata_reader: Callable[[], Mapping[str, object]] = focused_window_metadata,
        capture_reader: Callable[[Path], Path] = capture_focused_window,
    ) -> None:
        self._metadata_reader = metadata_reader
        self._capture_reader = capture_reader

    def inspect_focused_window(self) -> FocusedWindowMetadata:
        return FocusedWindowMetadata.from_mapping(self._metadata_reader())

    def capture_focused_window(self, window: FocusedWindowMetadata) -> bytes:
        with tempfile.TemporaryDirectory(prefix="fcc-appshot-") as temporary:
            image_path = self._capture_reader(Path(temporary))
            after = self.inspect_focused_window()
            if after.display_title != window.display_title:
                raise RuntimeError("focused window changed during capture")
            return image_path.read_bytes()


@dataclass(frozen=True, slots=True)
class _StaticFocusedWindowCapture:
    metadata: FocusedWindowMetadata
    image_bytes: bytes

    def inspect_focused_window(self) -> FocusedWindowMetadata:
        return self.metadata

    def capture_focused_window(self, window: FocusedWindowMetadata) -> bytes:
        if window != self.metadata:
            raise RuntimeError("focused window metadata changed before capture")
        return self.image_bytes


def build_appshot_attachment(
    image_path: Path,
    *,
    session_id: str,
    metadata: dict[str, str],
) -> AppshotAttachment:
    """Validate a local image and bind it to an explicit session id."""
    data = image_path.read_bytes()
    attachment, _ = capture_appshot(
        _StaticFocusedWindowCapture(
            metadata=FocusedWindowMetadata.from_mapping(metadata),
            image_bytes=data,
        ),
        TerminalSessionAssociation.explicit(session_id),
        policy=AppshotPolicy(),
        monotonic=lambda: 0.0,
    )
    return replace(attachment, image_path=image_path)


def appshot_queue_dir(root: Path | None = None) -> Path | None:
    """Return an explicitly configured queue directory, or no persistence."""
    if root is not None:
        return root.expanduser()
    configured = os.environ.get("FCC_APPSHOT_QUEUE")
    return Path(configured).expanduser() if configured else None


def enqueue_appshot(attachment: AppshotAttachment, *, root: Path | None = None) -> Path:
    """Persist one attachment only when a queue root is explicitly supplied."""
    queue_root = appshot_queue_dir(root)
    if queue_root is None:
        raise ValueError("Appshot persistence is disabled; supply an explicit queue")
    queue = FileAppshotQueue(queue_root)
    receipt = queue.enqueue(attachment)
    return queue.receipt_path(receipt)


def pending_appshots(session_id: str, *, root: Path | None = None) -> tuple[Path, ...]:
    """List only persisted receipts for one explicit session."""
    association = TerminalSessionAssociation.explicit(session_id)
    queue_root = appshot_queue_dir(root)
    if queue_root is None:
        return ()
    return tuple(sorted(queue_root.glob(f"{association.session_id}-*.json")))


def capture_and_enqueue_appshot(
    *,
    session_id: str,
    root: Path | None = None,
    source: FocusedWindowCapturePort | None = None,
    policy: AppshotPolicy | None = None,
    session_source: str = "explicit",
    monotonic: Callable[[], float] = time.monotonic,
    timestamp: Callable[[], datetime] | None = None,
) -> tuple[AppshotAttachment, AppshotReceipt | Path]:
    """Capture the focused window for one session without implicit persistence."""
    queue_root = appshot_queue_dir(root)
    queue: AppshotQueuePort
    file_queue: FileAppshotQueue | None = None
    if queue_root is None:
        queue = InMemoryAppshotQueue()
    else:
        file_queue = FileAppshotQueue(queue_root)
        queue = file_queue
    attachment, receipt = capture_appshot(
        source or MacOSFocusedWindowCapture(),
        TerminalSessionAssociation(session_id=session_id, source=session_source),
        queue=queue,
        policy=policy,
        monotonic=monotonic,
        timestamp=timestamp,
    )
    if file_queue is None:
        return attachment, receipt
    return (
        replace(attachment, image_path=file_queue.asset_path(receipt)),
        file_queue.receipt_path(receipt),
    )


def appshot_temp_dir() -> tempfile.TemporaryDirectory[str]:
    """Create a demand-only Appshot directory; callers own its cleanup."""
    return tempfile.TemporaryDirectory(prefix="fcc-appshot-")
