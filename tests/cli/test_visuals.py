import base64
from pathlib import Path

import pytest

from free_claude_code.cli.visuals import (
    build_appshot_attachment,
    enqueue_appshot,
    pending_appshots,
    render_attachment,
    render_attachment_card,
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
