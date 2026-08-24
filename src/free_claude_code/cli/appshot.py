"""Explicit focused-window Appshot helper for FCC-Claude sessions."""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .appshot_helpers import copy_appshot_path, inspect_appshot, open_appshot
from .visuals import (
    capture_and_enqueue_appshot,
    pending_appshots,
    render_terminal_preview,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fcc-appshot",
        description="Capture the focused macOS window for one FCC-Claude session.",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="explicit opaque Claude session id (or FCC_CLAUDE_SESSION_ID)",
    )
    parser.add_argument(
        "--queue",
        type=Path,
        default=None,
        help="local Appshot queue directory",
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--list",
        action="store_true",
        help="list queued receipts for the explicit session without capturing",
    )
    actions.add_argument(
        "--inspect",
        type=Path,
        metavar="RECEIPT",
        help="show redacted metadata for one persisted receipt",
    )
    actions.add_argument(
        "--open",
        dest="open_receipt",
        type=Path,
        metavar="RECEIPT",
        help="open one persisted image in the local default viewer",
    )
    actions.add_argument(
        "--copy-path",
        dest="copy_receipt",
        type=Path,
        metavar="RECEIPT",
        help="copy one persisted image path to the local clipboard",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="print metadata only instead of rendering a supported-terminal preview",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Capture one Appshot or perform one explicit persisted-queue action."""
    args = _parser().parse_args(argv)
    session_id = args.session_id or os.environ.get("FCC_CLAUDE_SESSION_ID", "")
    if args.list:
        if not session_id:
            raise SystemExit(
                "fcc-appshot --list requires --session-id or FCC_CLAUDE_SESSION_ID"
            )
        for receipt in pending_appshots(session_id, root=args.queue):
            print(receipt.name)
        return
    if args.inspect or args.open_receipt or args.copy_receipt:
        receipt = args.inspect or args.open_receipt or args.copy_receipt
        try:
            if args.inspect:
                print(inspect_appshot(receipt, root=args.queue))
            elif args.open_receipt:
                open_appshot(receipt, root=args.queue)
                print(f"opened: {receipt.name}")
            else:
                copy_appshot_path(receipt, root=args.queue)
                print(f"copied: {receipt.name}")
        except (OSError, RuntimeError, ValueError) as exc:
            print(
                f"Appshot helper failed: {type(exc).__name__}: {exc}", file=sys.stderr
            )
            raise SystemExit(1) from exc
        return
    if not session_id:
        raise SystemExit("fcc-appshot requires --session-id or FCC_CLAUDE_SESSION_ID")
    try:
        attachment, receipt = capture_and_enqueue_appshot(
            session_id=session_id,
            root=args.queue,
            session_source="explicit" if args.session_id else "environment",
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Appshot failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(attachment.confirmation())
    if not args.no_preview:
        try:
            print(
                render_terminal_preview(
                    attachment.image_bytes,
                    media_type=attachment.visual.media_type,
                    label=attachment.visual.label,
                )
            )
        except (OSError, ValueError) as exc:
            print(f"Preview unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
    if isinstance(receipt, Path):
        print(f"queued: {receipt.name}")
    else:
        print(f"queued: in-memory-only:{receipt.attachment_id}")


if __name__ == "__main__":
    main()
