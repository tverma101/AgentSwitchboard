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

_WindowBounds = tuple[int, int, int, int]


def _window_bounds(metadata: Mapping[str, object]) -> _WindowBounds:
    values: list[int] = []
    for name in ("x", "y", "width", "height"):
        value = metadata.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeError(f"focused window metadata is missing integer {name}")
        values.append(value)
    x, y, width, height = values
    if width <= 0 or height <= 0:
        raise RuntimeError("focused window metadata has invalid dimensions")
    return x, y, width, height


def capture_focused_window(output_dir: Path, bounds: _WindowBounds) -> Path:
    """Capture the inspected macOS window rectangle without interactive selection."""
    x, y, width, height = bounds
    if width <= 0 or height <= 0:
        raise ValueError("focused window bounds must have positive dimensions")
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "appshot.png"
    result = subprocess.run(
        [
            "screencapture",
            "-x",
            "-R",
            f"{x},{y},{width},{height}",
            str(destination),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not destination.is_file():
        raise RuntimeError(
            "Focused-window capture failed; grant Screen Recording access"
        )
    return destination


def focused_window_metadata() -> dict[str, object]:
    """Read focused-window identity and bounds through Accessibility metadata."""
    script = """
tell application "System Events"
    tell first process whose frontmost is true
        set frontWindow to front window
        set windowPosition to position of frontWindow
        set windowSize to size of frontWindow
        return name & linefeed & (value of attribute "AXTitle" of frontWindow) & linefeed & (item 1 of windowPosition as text) & linefeed & (item 2 of windowPosition as text) & linefeed & (item 1 of windowSize as text) & linefeed & (item 2 of windowSize as text)
    end tell
end tell
""".strip()
    result = subprocess.run(
        ["osascript", "-e", script], check=True, text=True, capture_output=True
    )
    parts = result.stdout.splitlines()
    if len(parts) < 6:
        raise RuntimeError("Accessibility did not return focused-window bounds")
    app = parts[0].strip() or "Unknown app"
    title = "\n".join(parts[1:-4]).strip()
    try:
        x, y, width, height = (int(float(value.strip())) for value in parts[-4:])
    except ValueError as exc:
        raise RuntimeError(
            "Accessibility returned invalid focused-window bounds"
        ) from exc
    metadata: dict[str, object] = {
        "app": app,
        "window": title,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    }
    _window_bounds(metadata)
    return metadata


class MacOSFocusedWindowCapture:
    """Small macOS adapter for the provider-neutral capture port.

    Accessibility identifies the focused window and its bounds before capture.
    The system ``screencapture`` command owns OS permission, but receives an
    explicit rectangle so Appshot never enters interactive window-selection
    mode. The adapter rejects focus or bounds changes before or during capture.
    """

    def __init__(
        self,
        *,
        metadata_reader: Callable[[], Mapping[str, object]] = focused_window_metadata,
        capture_reader: Callable[[Path, _WindowBounds], Path] = capture_focused_window,
    ) -> None:
        self._metadata_reader = metadata_reader
        self._capture_reader = capture_reader
        self._inspected_window: FocusedWindowMetadata | None = None
        self._inspected_bounds: _WindowBounds | None = None

    def inspect_focused_window(self) -> FocusedWindowMetadata:
        metadata = self._metadata_reader()
        window = FocusedWindowMetadata.from_mapping(metadata)
        self._inspected_window = window
        self._inspected_bounds = _window_bounds(metadata)
        return window

    def capture_focused_window(self, window: FocusedWindowMetadata) -> bytes:
        bounds = self._inspected_bounds
        if self._inspected_window is not window or bounds is None:
            raise RuntimeError(
                "focused window was not inspected by this capture source"
            )

        # Each inspection authorizes exactly one capture attempt. Clear the
        # retained target before any further OS reads so failure cannot reuse a
        # stale sensitive-window authorization.
        self._inspected_window = None
        self._inspected_bounds = None

        current_metadata = self._metadata_reader()
        current = FocusedWindowMetadata.from_mapping(current_metadata)
        if (
            current.display_title != window.display_title
            or _window_bounds(current_metadata) != bounds
        ):
            raise RuntimeError("focused window changed before capture")

        with tempfile.TemporaryDirectory(prefix="fcc-appshot-") as temporary:
            image_path = self._capture_reader(Path(temporary), bounds)
            after_metadata = self._metadata_reader()
            after = FocusedWindowMetadata.from_mapping(after_metadata)
            if (
                after.display_title != window.display_title
                or _window_bounds(after_metadata) != bounds
            ):
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
