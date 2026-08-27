"""Explicit local terminal presentation for ordinary image attachments."""

import argparse
import base64
import binascii
import io
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from free_claude_code.core.visual_attachments import (
    SUPPORTED_IMAGE_TYPES,
    VisualAttachmentError,
    validate_image_bytes,
)

from .terminal_preview import render_attachment, render_attachment_card

_CLIPBOARD_TIMEOUT_SECONDS = 5.0
_CLIPBOARD_SWIFT = """\
import AppKit
import Foundation

let pasteboard = NSPasteboard.general
if let data = pasteboard.data(forType: .png) {
    print(data.base64EncodedString())
    exit(0)
}
if let data = pasteboard.data(forType: .tiff),
   let image = NSImage(data: data),
   let tiff = image.tiffRepresentation,
   let bitmap = NSBitmapImageRep(data: tiff),
   let png = bitmap.representation(using: .png, properties: [:]) {
    print(png.base64EncodedString())
    exit(0)
}
FileHandle.standardError.write(Data("no image on clipboard\\n".utf8))
exit(1)
"""


class AttachmentSourceError(ValueError):
    """An image source could not be read without exposing its contents."""


def read_image_source(
    *,
    path: Path | None = None,
    clipboard: bool = False,
    label: str | None = None,
) -> tuple[bytes, str, str]:
    """Read one local image source and return bytes, media type, and label."""
    if (path is None) != clipboard:
        raise AttachmentSourceError("choose exactly one image path or clipboard source")

    if clipboard:
        data = _read_clipboard_image()
        source_label = label or "clipboard-image"
    else:
        assert path is not None
        source_path = path.expanduser()
        try:
            if not source_path.is_file():
                raise AttachmentSourceError("image path is not a regular file")
            data = source_path.read_bytes()
        except OSError as exc:
            raise AttachmentSourceError(
                f"could not read image file {source_path.name or 'attachment'}"
            ) from exc
        source_label = label or source_path.name or "attachment"

    media_type = _detect_media_type(data)
    validate_image_bytes(data, media_type=media_type, label=source_label)
    return data, media_type, source_label


def main(argv: Sequence[str] | None = None) -> None:
    """Render one ordinary image attachment without persisting or sending it."""
    args = _parser().parse_args(argv)
    try:
        data, media_type, label = read_image_source(
            path=args.path,
            clipboard=args.clipboard,
            label=args.label,
        )
        rendered = (
            render_attachment_card(data, media_type=media_type, label=label)
            if args.no_preview
            else render_attachment(data, media_type=media_type, label=label)
        )
    except (AttachmentSourceError, OSError, VisualAttachmentError) as exc:
        print(f"Attachment failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(rendered)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fcc-attachment",
        description="Show a local terminal confirmation for one image attachment.",
    )
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument(
        "--path",
        type=Path,
        metavar="IMAGE",
        help="local PNG, JPEG, or WebP file; bytes are read in memory only",
    )
    sources.add_argument(
        "--clipboard",
        action="store_true",
        help="read one PNG/TIFF image from the macOS clipboard in memory",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="optional short display label; defaults to the file name or clipboard-image",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="print the metadata card without terminal image escape sequences",
    )
    return parser


def _read_clipboard_image() -> bytes:
    if sys.platform != "darwin":
        raise AttachmentSourceError("clipboard image input requires macOS")
    swift = shutil.which("swift")
    if swift is None:
        raise AttachmentSourceError(
            "Swift is unavailable; use --path or install the macOS command-line tools"
        )
    try:
        result = subprocess.run(
            [swift, "-e", _CLIPBOARD_SWIFT],
            check=False,
            capture_output=True,
            text=True,
            timeout=_CLIPBOARD_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AttachmentSourceError("could not read the macOS clipboard") from exc
    if result.returncode != 0:
        raise AttachmentSourceError(
            "no PNG or TIFF image is available on the clipboard"
        )
    encoded = result.stdout.strip()
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AttachmentSourceError(
            "macOS clipboard returned invalid image data"
        ) from exc
    if not data:
        raise AttachmentSourceError("macOS clipboard returned an empty image")
    return data


def _detect_media_type(data: bytes) -> str:
    try:
        with Image.open(io.BytesIO(data)) as image:
            media_type = image.get_format_mimetype()
    except (OSError, ValueError) as exc:
        raise AttachmentSourceError("image bytes are corrupt or unreadable") from exc
    if media_type not in SUPPORTED_IMAGE_TYPES:
        raise VisualAttachmentError(
            f"Unsupported image media type: {media_type or 'unknown'}"
        )
    return media_type


__all__ = ["AttachmentSourceError", "main", "read_image_source"]
