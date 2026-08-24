import io

from PIL import Image

from free_claude_code.cli.visuals import (
    _thumbnail_for_terminal,
    clear_terminal_preview_cache,
    detect_terminal_capabilities,
    render_attachment_card,
    render_terminal_preview,
    terminal_preview_cache_size,
)


def _png_bytes(color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (4, 3), color).save(output, format="PNG")
    return output.getvalue()


def test_terminal_detection_fails_closed_for_non_tty_ssh_and_multiplexers() -> None:
    assert (
        detect_terminal_capabilities(
            {"TERM_PROGRAM": "iTerm.app"}, is_tty=False
        ).reason
        == "stdout-not-a-tty"
    )
    ssh = detect_terminal_capabilities(
        {"TERM_PROGRAM": "iTerm.app", "SSH_TTY": "/dev/ttys001"},
        is_tty=True,
    )
    assert ssh.protocol is None
    assert ssh.remote is True
    assert ssh.reason == "ssh-session"
    tmux = detect_terminal_capabilities(
        {"TERM_PROGRAM": "iTerm.app", "TMUX": "1"},
        is_tty=True,
    )
    screen = detect_terminal_capabilities(
        {"TERM_PROGRAM": "iTerm.app", "STY": "1"},
        is_tty=True,
    )
    assert (tmux.protocol, tmux.multiplexer) == (None, "tmux")
    assert (screen.protocol, screen.multiplexer) == (None, "screen")


def test_fail_closed_sessions_emit_only_metadata_card() -> None:
    data = _png_bytes()
    rendered = render_terminal_preview(
        data,
        media_type="image/png",
        label="shot.png",
        env={"TERM_PROGRAM": "iTerm.app", "SSH_CONNECTION": "remote"},
        is_tty=True,
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


def test_thumbnail_cache_is_hash_bounded_across_many_previews() -> None:
    clear_terminal_preview_cache()
    for index in range(20):
        render_terminal_preview(
            _png_bytes((index, 255 - index, (index * 17) % 255)),
            media_type="image/png",
            label=f"shot-{index}.png",
            env={"TERM_PROGRAM": "iTerm.app"},
            is_tty=True,
        )

    assert terminal_preview_cache_size() == 8
    clear_terminal_preview_cache()
    assert terminal_preview_cache_size() == 0


def test_large_thumbnail_respects_byte_and_edge_bounds() -> None:
    output = io.BytesIO()
    Image.new("RGB", (2400, 1800), (10, 20, 30)).save(output, format="PNG")

    preview, media_type = _thumbnail_for_terminal(
        output.getvalue(),
        media_type="image/png",
    )

    assert len(preview) <= 512 * 1024
    with Image.open(io.BytesIO(preview)) as image:
        assert max(image.size) <= 1024
    assert media_type in {"image/png", "image/jpeg"}
