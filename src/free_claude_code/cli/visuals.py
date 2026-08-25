"""Local terminal visual UX and focused-window Appshot capture."""

import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

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

from .terminal_preview import (
    TerminalImageCapabilities,
    TerminalPreviewSession,
    clear_terminal_preview_cache,
    detect_terminal_capabilities,
    render_attachment,
    render_attachment_card,
    render_terminal_preview,
    terminal_image_protocol,
    terminal_preview_cache_size,
)


def capture_focused_window(output_dir: Path) -> Path:
    """Capture only the focused macOS window using the system screenshot tool."""
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "appshot.png"
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
    selection. This adapter binds inspected metadata to captured bytes and
    rejects a focus change during the operation.
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


__all__ = [
    "MacOSFocusedWindowCapture",
    "TerminalImageCapabilities",
    "TerminalPreviewSession",
    "appshot_queue_dir",
    "appshot_temp_dir",
    "build_appshot_attachment",
    "capture_and_enqueue_appshot",
    "capture_focused_window",
    "clear_terminal_preview_cache",
    "detect_terminal_capabilities",
    "enqueue_appshot",
    "focused_window_metadata",
    "pending_appshots",
    "render_attachment",
    "render_attachment_card",
    "render_terminal_preview",
    "terminal_image_protocol",
    "terminal_preview_cache_size",
]
