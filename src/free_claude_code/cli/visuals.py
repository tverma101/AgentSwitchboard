"""Local terminal visual UX and focused-window Appshot capture."""

import os
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

from .macos_screenshot import (
    capture_focused_window,
    ensure_screen_recording_permission,
    focused_window_metadata,
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


def _window_id(metadata: Mapping[str, object]) -> int:
    value = metadata.get("window_id")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeError("focused window metadata is missing valid window_id")
    return value


class MacOSFocusedWindowCapture:
    """Small macOS adapter for the provider-neutral capture port.

    A Codex-derived Swift helper identifies the frontmost layer-0 Core Graphics
    window directly, so Appshot does not need Accessibility permission or an
    AppleScript/JXA remapping pass. Screen Recording is preflighted once before
    inspection. Identity, bounds, and window id must remain stable before and
    after the one authorized capture attempt.
    """

    def __init__(
        self,
        *,
        metadata_reader: Callable[[], Mapping[str, object]] = focused_window_metadata,
        capture_reader: Callable[[Path, int], Path] = capture_focused_window,
        permission_preflight: Callable[[], None] = ensure_screen_recording_permission,
    ) -> None:
        self._metadata_reader = metadata_reader
        self._capture_reader = capture_reader
        self._permission_preflight = permission_preflight
        self._permission_checked = False
        self._inspected_window: FocusedWindowMetadata | None = None
        self._inspected_bounds: _WindowBounds | None = None
        self._inspected_window_id: int | None = None

    def inspect_focused_window(self) -> FocusedWindowMetadata:
        if not self._permission_checked:
            self._permission_preflight()
            self._permission_checked = True
        metadata = self._metadata_reader()
        window = FocusedWindowMetadata.from_mapping(metadata)
        self._inspected_window = window
        self._inspected_bounds = _window_bounds(metadata)
        self._inspected_window_id = _window_id(metadata)
        return window

    def capture_focused_window(self, window: FocusedWindowMetadata) -> bytes:
        bounds = self._inspected_bounds
        window_id = self._inspected_window_id
        if self._inspected_window is not window or bounds is None or window_id is None:
            raise RuntimeError(
                "focused window was not inspected by this capture source"
            )

        # Each inspection authorizes exactly one capture attempt. Clear the
        # retained target before any further OS reads so failure cannot reuse a
        # stale sensitive-window authorization.
        self._inspected_window = None
        self._inspected_bounds = None
        self._inspected_window_id = None

        current_metadata = self._metadata_reader()
        current = FocusedWindowMetadata.from_mapping(current_metadata)
        if (
            current.display_title != window.display_title
            or _window_bounds(current_metadata) != bounds
            or _window_id(current_metadata) != window_id
        ):
            raise RuntimeError("focused window changed before capture")

        with tempfile.TemporaryDirectory(prefix="fcc-appshot-") as temporary:
            image_path = self._capture_reader(Path(temporary), window_id)
            after_metadata = self._metadata_reader()
            after = FocusedWindowMetadata.from_mapping(after_metadata)
            if (
                after.display_title != window.display_title
                or _window_bounds(after_metadata) != bounds
                or _window_id(after_metadata) != window_id
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
