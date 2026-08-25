import base64
from pathlib import Path

import pytest

from free_claude_code.cli.visuals import (
    MacOSFocusedWindowCapture,
    build_appshot_attachment,
    capture_focused_window,
    enqueue_appshot,
    pending_appshots,
    render_attachment,
    render_attachment_card,
    render_terminal_preview,
    terminal_image_protocol,
)


def test_terminal_protocol_detection_and_fallback() -> None:
    assert terminal_image_protocol({"TERM_PROGRAM": "iTerm.app"}) == "iterm2"
    assert terminal_image_protocol({"TERM": "dumb"}) is None
    assert terminal_image_protocol({"TERM_PROGRAM": "iTerm.app", "TMUX": "1"}) is None
    assert terminal_image_protocol({"TERM": "xterm-sixel"}) == "sixel"


def test_fallback_card_is_compact() -> None:
    import io

    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (3, 2), "red").save(output, format="PNG")

    card = render_attachment_card(
        output.getvalue(), media_type="image/png", label="screenshot.png"
    )
    assert card.startswith("[img ") and "screenshot.png" in card


def test_supported_protocol_preview_is_local_and_keeps_confirmation() -> None:
    import base64

    data = _png_bytes()
    rendered = render_attachment(
        data,
        media_type="image/png",
        label="clipboard-image",
        env={"TERM_PROGRAM": "iTerm.app"},
    )
    assert rendered.startswith("\x1b]1337;File=")
    assert base64.b64encode(data).decode() in rendered
    assert "attached" in rendered


def test_terminal_preview_downscales_large_images_without_changing_receipt() -> None:
    import io

    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (1600, 1200), "red").save(output, format="PNG")
    data = output.getvalue()

    rendered = render_terminal_preview(
        data,
        media_type="image/png",
        label="window-shot",
        env={"TERM_PROGRAM": "iTerm.app"},
    )

    assert rendered.startswith("\x1b]1337;File=")
    assert "window-shot" in rendered
    assert "1600\u00d71200" in rendered
    assert base64.b64encode(data).decode() not in rendered


def test_terminal_preview_falls_back_to_metadata_for_sixel() -> None:
    data = _png_bytes()
    rendered = render_terminal_preview(
        data,
        media_type="image/png",
        label="window-shot",
        env={"TERM": "xterm-sixel"},
    )

    assert rendered.startswith("[img ")
    assert "\x1b" not in rendered


def test_capture_focused_window_uses_window_id_without_region_or_interaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        Path(command[-1]).write_bytes(_png_bytes())
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "free_claude_code.cli.macos_screenshot.subprocess.run", fake_run
    )

    image = capture_focused_window(tmp_path, 7312)

    assert image.read_bytes() == _png_bytes()
    assert commands == [
        [
            "screencapture",
            "-x",
            "-l",
            "7312",
            str(tmp_path / "appshot.png"),
        ]
    ]
    assert "-R" not in commands[0]
    assert "-w" not in commands[0]
    assert "-i" not in commands[0]


def test_macos_appshot_capture_uses_the_inspected_window_id() -> None:
    metadata = {
        "app": "Safari",
        "window": "localhost:3000",
        "x": 12,
        "y": 34,
        "width": 800,
        "height": 600,
        "window_id": 7312,
    }
    captures: list[int] = []
    permission_checks: list[None] = []

    def read_metadata() -> dict[str, object]:
        return dict(metadata)

    def capture_window(output_dir: Path, window_id: int) -> Path:
        captures.append(window_id)
        image = output_dir / "appshot.png"
        image.write_bytes(_png_bytes())
        return image

    source = MacOSFocusedWindowCapture(
        metadata_reader=read_metadata,
        capture_reader=capture_window,
        permission_preflight=lambda: permission_checks.append(None),
    )
    inspected = source.inspect_focused_window()

    assert inspected.width == 800
    assert inspected.height == 600
    assert source.capture_focused_window(inspected) == _png_bytes()
    assert captures == [7312]
    assert permission_checks == [None]


def test_macos_appshot_rejects_bounds_change_before_reading_pixels() -> None:
    metadata = {
        "app": "Safari",
        "window": "localhost:3000",
        "x": 12,
        "y": 34,
        "width": 800,
        "height": 600,
        "window_id": 7312,
    }
    captures: list[int] = []

    def read_metadata() -> dict[str, object]:
        return dict(metadata)

    def capture_window(output_dir: Path, window_id: int) -> Path:
        captures.append(window_id)
        image = output_dir / "appshot.png"
        image.write_bytes(_png_bytes())
        return image

    source = MacOSFocusedWindowCapture(
        metadata_reader=read_metadata,
        capture_reader=capture_window,
        permission_preflight=lambda: None,
    )
    inspected = source.inspect_focused_window()
    metadata["x"] = 99

    with pytest.raises(RuntimeError, match="changed before capture"):
        source.capture_focused_window(inspected)

    assert captures == []


def test_macos_appshot_rejects_window_id_change_before_reading_pixels() -> None:
    metadata = {
        "app": "Safari",
        "window": "localhost:3000",
        "x": 12,
        "y": 34,
        "width": 800,
        "height": 600,
        "window_id": 7312,
    }
    captures: list[int] = []

    def read_metadata() -> dict[str, object]:
        return dict(metadata)

    def capture_window(output_dir: Path, window_id: int) -> Path:
        captures.append(window_id)
        image = output_dir / "appshot.png"
        image.write_bytes(_png_bytes())
        return image

    source = MacOSFocusedWindowCapture(
        metadata_reader=read_metadata,
        capture_reader=capture_window,
        permission_preflight=lambda: None,
    )
    inspected = source.inspect_focused_window()
    metadata["window_id"] = 7313

    with pytest.raises(RuntimeError, match="changed before capture"):
        source.capture_focused_window(inspected)

    assert captures == []


def test_appshot_queue_is_explicit_session_scoped_and_metadata_only(
    tmp_path: Path,
) -> None:
    image = tmp_path / "appshot.png"
    image.write_bytes(_png_bytes())
    attachment = build_appshot_attachment(
        image,
        session_id="session-1",
        metadata={"app": "Safari", "window": "localhost:3000"},
    )

    receipt = enqueue_appshot(attachment, root=tmp_path / "queue")
    assert receipt.exists()
    assert pending_appshots("session-1", root=tmp_path / "queue") == (receipt,)
    assert "Safari" in attachment.confirmation()
    assert base64.b64encode(_png_bytes()).decode() not in receipt.read_text()


def test_appshot_rejects_path_like_session_ids(tmp_path: Path) -> None:
    image = tmp_path / "appshot.png"
    image.write_bytes(_png_bytes())
    with pytest.raises(ValueError, match="session_id"):
        build_appshot_attachment(image, session_id="../wrong", metadata={})


def _png_bytes() -> bytes:
    import io

    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (3, 2), "red").save(output, format="PNG")
    return output.getvalue()
