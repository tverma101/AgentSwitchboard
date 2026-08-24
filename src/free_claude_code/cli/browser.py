"""Terminal-only local Chrome/Chromium CDP helper."""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from typing import Any

from free_claude_code.application.browser_cdp import (
    BrowserCdpError,
    ChromeCdpBrowserBridge,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fcc-browser",
        description="Use an explicitly enabled local Chrome/Chromium CDP session.",
    )
    parser.add_argument(
        "--cdp-url",
        default=os.environ.get("FCC_BROWSER_CDP_URL", "http://127.0.0.1:9222"),
        help="loopback CDP endpoint (or FCC_BROWSER_CDP_URL)",
    )
    parser.add_argument(
        "--allow-existing-session",
        action="store_true",
        help="explicitly permit attaching to the already-running browser session",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list-tabs", help="list bounded tab metadata")

    snapshot = commands.add_parser(
        "snapshot-dom", help="inspect bounded interactive DOM"
    )
    snapshot.add_argument("tab_id")

    action = commands.add_parser("action", help="perform one bounded browser action")
    action.add_argument("tab_id")
    action.add_argument(
        "action",
        choices=("navigate", "click", "type", "scroll", "query"),
    )
    action.add_argument("--url")
    action.add_argument("--selector")
    action.add_argument("--text")
    action.add_argument("--delta-x", type=float, default=0)
    action.add_argument("--delta-y", type=float, default=0)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run one local CDP command and print metadata-only JSON."""
    args = _parser().parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except (BrowserCdpError, OSError, ValueError) as exc:
        print(f"fcc-browser failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))


async def _run(args: argparse.Namespace) -> object:
    bridge = ChromeCdpBrowserBridge(
        args.cdp_url,
        allow_existing_session=args.allow_existing_session,
    )
    try:
        if args.command == "list-tabs":
            return list(await bridge.list_tabs())
        if args.command == "snapshot-dom":
            return await bridge.snapshot_dom(args.tab_id)
        return await bridge.perform(
            args.tab_id,
            args.action,
            _action_arguments(args),
        )
    finally:
        await bridge.aclose()


def _action_arguments(args: argparse.Namespace) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for name in ("url", "selector", "text"):
        value = getattr(args, name, None)
        if value is not None:
            values[name] = value
    if args.action == "scroll":
        values["delta_x"] = args.delta_x
        values["delta_y"] = args.delta_y
    return values


if __name__ == "__main__":
    main()
