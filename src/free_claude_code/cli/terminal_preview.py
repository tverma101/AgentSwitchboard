"""Bounded, local-only terminal image presentation.

This module owns terminal capability detection and preview bytes only. It does
not capture Appshots, persist images, alter model payloads, or call providers.
"""

import base64
import hashlib
import io
import os
import re
import sys
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from PIL import Image

from free_claude_code.core.visual_attachments import (
    VisualAttachmentError,
    validate_image_bytes,
)

_PREVIEW_MAX_EDGE = 1024
_PREVIEW_MAX_BYTES = 512 * 1024
_PREVIEW_CACHE_LIMIT = 8
_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]")
_MAX_DISPLAY_LABEL_LENGTH = 64


def _safe_display_label(label: str) -> str:
    """Reduce a local label to a compact terminal-safe basename."""
    normalized = _CONTROL_CHARACTER_RE.sub("/", label.replace("\\", "/"))
    basename = PurePosixPath(normalized).name.strip()
    basename = " ".join(basename.split())
    if not basename or basename in {".", ".."}:
        return "attachment"
    if len(basename) > _MAX_DISPLAY_LABEL_LENGTH:
        return basename[: _MAX_DISPLAY_LABEL_LENGTH - 3] + "..."
    return basename


@dataclass(frozen=True, slots=True)
class TerminalImageCapabilities:
    """One terminal capability probe reused for an attachment session."""

    protocol: str | None
    is_tty: bool
    remote: bool
    multiplexer: str | None
    reason: str

    @property
    def supports_inline_preview(self) -> bool:
        return self.protocol in {"iterm2", "kitty"}


def detect_terminal_capabilities(
    env: Mapping[str, str] | None = None,
    *,
    is_tty: bool | None = None,
) -> TerminalImageCapabilities:
    """Probe terminal presentation once and fail closed when ambiguous.

    Supplying an explicit ``env`` is the deterministic test seam and defaults
    to TTY=true unless ``is_tty`` is also supplied. Normal runtime calls use the
    process environment and the real stdout TTY state.
    """
    values = os.environ if env is None else env
    tty = (
        (sys.stdout.isatty() if env is None else True)
        if is_tty is None
        else is_tty
    )
    if not tty:
        return TerminalImageCapabilities(None, False, False, None, "stdout-not-a-tty")
    if values.get("SSH_CONNECTION") or values.get("SSH_TTY"):
        return TerminalImageCapabilities(None, True, True, None, "ssh-session")
    if values.get("TMUX"):
        return TerminalImageCapabilities(None, True, False, "tmux", "multiplexer")
    if values.get("STY"):
        return TerminalImageCapabilities(None, True, False, "screen", "multiplexer")
    if values.get("TERM_PROGRAM") == "iTerm.app" or values.get("LC_TERMINAL") == "iTerm2":
        return TerminalImageCapabilities("iterm2", True, False, None, "iterm2")
    if values.get("KITTY_WINDOW_ID") or values.get("TERM", "").lower().startswith(
        "xterm-kitty"
    ):
        return TerminalImageCapabilities("kitty", True, False, None, "kitty")
    if values.get("SIXEL_SUPPORT", "").lower() in {"1", "true", "yes"} or (
        "sixel" in values.get("TERM", "").lower()
    ):
        return TerminalImageCapabilities("sixel", True, False, None, "sixel")
    return TerminalImageCapabilities(None, True, False, None, "unsupported-terminal")


def terminal_image_protocol(
    env: Mapping[str, str] | None = None,
    *,
    is_tty: bool | None = None,
) -> str | None:
    """Return a detected image protocol, including unsupported Sixel metadata."""
    return detect_terminal_capabilities(env, is_tty=is_tty).protocol


@dataclass(frozen=True, slots=True)
class TerminalPreviewSession:
    """Renderer that performs terminal detection once at session setup."""

    capabilities: TerminalImageCapabilities

    @classmethod
    def from_environment(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        is_tty: bool | None = None,
    ) -> "TerminalPreviewSession":
        return cls(detect_terminal_capabilities(env, is_tty=is_tty))

    def render(self, data: bytes, *, media_type: str, label: str) -> str:
        return render_terminal_preview(
            data,
            media_type=media_type,
            label=label,
            capabilities=self.capabilities,
        )


_THUMBNAIL_CACHE: OrderedDict[tuple[str, str], tuple[bytes, str]] = OrderedDict()


def render_attachment_card(data: bytes, *, media_type: str, label: str) -> str:
    """Produce the compact fallback card with no local path disclosure."""
    return validate_image_bytes(
        data,
        media_type=media_type,
        label=_safe_display_label(label),
    ).card()


def render_attachment(
    data: bytes,
    *,
    media_type: str,
    label: str,
    env: Mapping[str, str] | None = None,
    is_tty: bool | None = None,
    capabilities: TerminalImageCapabilities | None = None,
) -> str:
    return render_terminal_preview(
        data,
        media_type=media_type,
        label=label,
        env=env,
        is_tty=is_tty,
        capabilities=capabilities,
    )


def render_terminal_preview(
    data: bytes,
    *,
    media_type: str,
    label: str,
    env: Mapping[str, str] | None = None,
    is_tty: bool | None = None,
    capabilities: TerminalImageCapabilities | None = None,
) -> str:
    """Render a bounded local preview plus the original metadata receipt."""
    receipt = validate_image_bytes(
        data,
        media_type=media_type,
        label=_safe_display_label(label),
    )
    detected = capabilities or detect_terminal_capabilities(env, is_tty=is_tty)
    if not detected.supports_inline_preview:
        return receipt.card()
    try:
        preview_data, preview_type = _thumbnail_for_terminal(
            data,
            media_type=media_type,
        )
    except VisualAttachmentError:
        return receipt.card()
    if detected.protocol == "iterm2":
        rendered = _iterm2_image(preview_data, media_type=preview_type)
    elif detected.protocol == "kitty":
        rendered = _kitty_image(preview_data)
    else:
        return receipt.card()
    return f"{rendered}\n{receipt.card()}"


def _thumbnail_for_terminal(data: bytes, *, media_type: str) -> tuple[bytes, str]:
    """Return a hash-cached preview that never exceeds the byte/edge bounds."""
    cache_key = (hashlib.sha256(data).hexdigest(), media_type)
    cached = _THUMBNAIL_CACHE.get(cache_key)
    if cached is not None:
        _THUMBNAIL_CACHE.move_to_end(cache_key)
        return cached
    with Image.open(io.BytesIO(data)) as source:
        if len(data) <= _PREVIEW_MAX_BYTES and max(source.size) <= _PREVIEW_MAX_EDGE:
            result = (data, media_type)
        else:
            result = _encode_bounded_thumbnail(source)
    _THUMBNAIL_CACHE[cache_key] = result
    _THUMBNAIL_CACHE.move_to_end(cache_key)
    while len(_THUMBNAIL_CACHE) > _PREVIEW_CACHE_LIMIT:
        _THUMBNAIL_CACHE.popitem(last=False)
    return result


def _encode_bounded_thumbnail(source: Image.Image) -> tuple[bytes, str]:
    source_rgb = source.convert("RGB")
    edge = min(_PREVIEW_MAX_EDGE, max(source_rgb.size))
    while edge >= 128:
        image = source_rgb.copy()
        image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        for quality in (80, 65, 50, 35):
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True)
            preview = output.getvalue()
            if len(preview) <= _PREVIEW_MAX_BYTES:
                return preview, "image/jpeg"
        edge //= 2
    raise VisualAttachmentError("Terminal preview exceeds the 512 KiB limit")


def clear_terminal_preview_cache() -> None:
    _THUMBNAIL_CACHE.clear()


def terminal_preview_cache_size() -> int:
    return len(_THUMBNAIL_CACHE)


def _iterm2_image(data: bytes, *, media_type: str) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return (
        "\x1b]1337;File="
        "inline=1;preserveAspectRatio=1;"
        f"size={len(data)};type={media_type}:{encoded}\x07"
    )


def _kitty_image(data: bytes) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    chunks = [encoded[index : index + 4096] for index in range(0, len(encoded), 4096)]
    return "".join(
        f"\x1b_Ga=T,f=100,t=d,m={int(index < len(chunks) - 1)};{chunk}\x1b\\"
        for index, chunk in enumerate(chunks)
    )


__all__ = [
    "TerminalImageCapabilities",
    "TerminalPreviewSession",
    "clear_terminal_preview_cache",
    "detect_terminal_capabilities",
    "render_attachment",
    "render_attachment_card",
    "render_terminal_preview",
    "terminal_image_protocol",
    "terminal_preview_cache_size",
]
