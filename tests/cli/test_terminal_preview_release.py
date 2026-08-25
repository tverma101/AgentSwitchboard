import base64
import io

import pytest
from PIL import Image

from free_claude_code.cli.terminal_preview import (
    clear_terminal_preview_cache,
    render_attachment_card,
    render_terminal_preview,
    terminal_preview_cache_size,
)


def _png_bytes(color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (4, 3), color).save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize(
    ("env", "is_tty"),
    [
        ({"TERM_PROGRAM": "iTerm.app"}, False),
        ({"TERM_PROGRAM": "iTerm.app", "SSH_TTY": "/dev/ttys001"}, True),
        ({"TERM_PROGRAM": "iTerm.app", "TMUX": "1"}, True),
        ({"TERM_PROGRAM": "iTerm.app", "STY": "1"}, True),
    ],
)
def test_blocked_terminal_contexts_never_emit_inline_escape_sequences(
    env: dict[str, str], is_tty: bool
) -> None:
    rendered = render_terminal_preview(
        _png_bytes(),
        media_type="image/png",
        label="shot.png",
        env=env,
        is_tty=is_tty,
    )

    assert rendered.startswith("[img ")
    assert "\x1b" not in rendered


def test_terminal_card_hides_full_path_and_control_characters() -> None:
    card = render_attachment_card(
        _png_bytes(),
        media_type="image/png",
        label="/Users/private/secret\x1b[31m-shot.png",
    )

    assert "Users" not in card
    assert "/Users/private" not in card
    assert "\x1b" not in card
    assert "31m-shot.png" in card


def test_preview_cache_reuses_content_and_stays_bounded_through_public_renderer() -> None:
    clear_terminal_preview_cache()
    env = {"TERM_PROGRAM": "iTerm.app"}
    first = _png_bytes()

    render_terminal_preview(
        first,
        media_type="image/png",
        label="first.png",
        env=env,
        is_tty=True,
    )
    render_terminal_preview(
        first,
        media_type="image/png",
        label="same-bytes-different-label.png",
        env=env,
        is_tty=True,
    )
    assert terminal_preview_cache_size() == 1

    for index in range(20):
        render_terminal_preview(
            _png_bytes((index, 255 - index, (index * 17) % 255)),
            media_type="image/png",
            label=f"shot-{index}.png",
            env=env,
            is_tty=True,
        )

    assert 1 <= terminal_preview_cache_size() <= 8
    clear_terminal_preview_cache()


def test_large_public_preview_emits_only_bounded_thumbnail_bytes() -> None:
    output = io.BytesIO()
    Image.new("RGB", (2400, 1800), (10, 20, 30)).save(output, format="PNG")

    rendered = render_terminal_preview(
        output.getvalue(),
        media_type="image/png",
        label="large.png",
        env={"TERM_PROGRAM": "iTerm.app"},
        is_tty=True,
    )

    escape_line = rendered.split("\n", maxsplit=1)[0]
    assert escape_line.startswith("\x1b]1337;File=")
    encoded = escape_line.rsplit(":", maxsplit=1)[1].removesuffix("\x07")
    preview = base64.b64decode(encoded, validate=True)

    assert len(preview) <= 512 * 1024
    with Image.open(io.BytesIO(preview)) as image:
        assert max(image.size) <= 1024
