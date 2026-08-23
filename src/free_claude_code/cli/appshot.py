"""Explicit focused-window Appshot helper for FCC-Claude sessions."""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .visuals import capture_and_enqueue_appshot


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fcc-appshot",
        description="Capture the focused macOS window for one FCC-Claude session.",
    )
    parser.add_argument(
        "--session-id",
        default=os.environ.get("FCC_CLAUDE_SESSION_ID", ""),
        help="explicit opaque Claude session id (or FCC_CLAUDE_SESSION_ID)",
    )
    parser.add_argument(
        "--queue",
        type=Path,
        default=None,
        help="local Appshot queue directory",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Capture one Appshot and print only local metadata."""
    args = _parser().parse_args(argv)
    if not args.session_id:
        raise SystemExit("fcc-appshot requires --session-id or FCC_CLAUDE_SESSION_ID")
    try:
        attachment, receipt = capture_and_enqueue_appshot(
            session_id=args.session_id,
            root=args.queue,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Appshot failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(attachment.confirmation())
    print(f"queued: {receipt.name}")


if __name__ == "__main__":
    main()
