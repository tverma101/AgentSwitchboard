import base64
import io
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from free_claude_code.core.appshot import (
    AppshotContractError,
    AppshotPolicy,
    FileAppshotQueue,
    FocusedWindowMetadata,
    InMemoryAppshotQueue,
    SensitiveAppshotError,
    TerminalSessionAssociation,
    capture_appshot,
)
from free_claude_code.core.visual_attachments import VisualAttachmentError


class FakeFocusedWindowCapture:
    def __init__(self, metadata: FocusedWindowMetadata, image_bytes: bytes) -> None:
        self.metadata = metadata
        self.image_bytes = image_bytes
        self.calls: list[object] = []

    def inspect_focused_window(self) -> FocusedWindowMetadata:
        self.calls.append("inspect")
        return self.metadata

    def capture_focused_window(self, window: FocusedWindowMetadata) -> bytes:
        self.calls.append(("capture", window))
        return self.image_bytes


def test_capture_port_binds_window_and_records_deterministic_latency() -> None:
    image = _png_bytes()
    metadata = FocusedWindowMetadata(
        app_name="Editor\x00",
        window_title="  main.py\n",
        accessibility_summary="button: Run",
    )
    source = FakeFocusedWindowCapture(metadata, image)
    queue = InMemoryAppshotQueue()
    ticks = iter((10.0, 10.125))

    attachment, receipt = capture_appshot(
        source,
        TerminalSessionAssociation.explicit("session-1"),
        queue=queue,
        monotonic=lambda: next(ticks),
        timestamp=lambda: datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
    )

    assert source.calls == ["inspect", ("capture", metadata)]
    assert attachment.metadata.app_name == "Editor"
    assert attachment.metadata.window_title == "main.py"
    assert attachment.metadata.accessibility_summary == "button: Run"
    assert attachment.capture_latency_ms == 125.0
    assert receipt.persisted is False
    assert receipt.asset_name is None
    assert receipt.captured_at == "2026-08-24T12:00:00.000Z"
    assert queue.read_asset(receipt) == image


def test_sensitive_app_is_denied_before_capture() -> None:
    source = FakeFocusedWindowCapture(
        FocusedWindowMetadata(app_name="1Password", window_title="Vault"),
        _png_bytes(),
    )

    with pytest.raises(SensitiveAppshotError):
        capture_appshot(
            source,
            TerminalSessionAssociation.explicit("session-1"),
        )

    assert source.calls == ["inspect"]


def test_default_queue_is_non_persistent() -> None:
    source = FakeFocusedWindowCapture(
        FocusedWindowMetadata(app_name="Safari"),
        _png_bytes(),
    )

    _, receipt = capture_appshot(
        source,
        TerminalSessionAssociation.explicit("session-1"),
    )

    assert receipt.persisted is False
    assert receipt.asset_name is None


def test_in_memory_queue_deduplicates_per_terminal_session() -> None:
    image = _png_bytes()
    queue = InMemoryAppshotQueue()
    source = FakeFocusedWindowCapture(
        FocusedWindowMetadata(app_name="Safari", window_title="localhost:3000"),
        image,
    )
    session_one = TerminalSessionAssociation.explicit("session-1")
    session_two = TerminalSessionAssociation.explicit("session-2")

    _, first = capture_appshot(source, session_one, queue=queue)
    _, duplicate = capture_appshot(source, session_one, queue=queue)
    _, other_session = capture_appshot(source, session_two, queue=queue)

    assert first.deduplicated is False
    assert duplicate.deduplicated is True
    assert other_session.deduplicated is False
    assert len(queue.pending(session_one)) == 1
    assert len(queue.pending(session_two)) == 1


def test_file_queue_is_explicit_and_receipt_is_sanitized(tmp_path: Path) -> None:
    image = _png_bytes()
    queue = FileAppshotQueue(tmp_path / "queue")
    source = FakeFocusedWindowCapture(
        FocusedWindowMetadata(
            app_name="Safari",
            window_title="localhost:3000",
            accessibility_summary="private AX text",
        ),
        image,
    )
    session = TerminalSessionAssociation.explicit("session-1")

    attachment, receipt = capture_appshot(source, session, queue=queue)
    receipt_path = queue.receipt_path(receipt)
    serialized = receipt_path.read_text(encoding="utf-8")

    assert receipt.persisted is True
    assert receipt.asset_name == f"session-1/{receipt.attachment_id}.png"
    assert str(tmp_path) not in serialized
    assert base64.b64encode(image).decode() not in serialized
    assert "private AX text" not in serialized
    assert '"sha256"' in serialized
    assert queue.read_asset(receipt) == image

    duplicate = queue.enqueue(attachment)
    assert duplicate.deduplicated is True
    assert len(queue.pending(session)) == 1


def test_size_policy_is_checked_before_queue_persistence() -> None:
    image = _png_bytes()
    queue = InMemoryAppshotQueue()
    source = FakeFocusedWindowCapture(
        FocusedWindowMetadata(app_name="Safari"),
        image,
    )

    with pytest.raises(VisualAttachmentError, match="exceeds"):
        capture_appshot(
            source,
            TerminalSessionAssociation.explicit("session-1"),
            queue=queue,
            policy=AppshotPolicy(max_bytes=len(image) - 1),
        )

    assert queue.pending(TerminalSessionAssociation.explicit("session-1")) == ()


def test_session_association_rejects_path_like_targets() -> None:
    with pytest.raises(AppshotContractError, match="session_id"):
        TerminalSessionAssociation.explicit("../wrong")


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (3, 2), "red").save(output, format="PNG")
    return output.getvalue()
