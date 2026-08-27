#!/usr/bin/env python3
"""Run the bounded local Codex browser-plugin device canary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from free_claude_code.runtime.codex_browser_helper import CodexBrowserHelperAdapter
from smoke.lib.codex_browser_device import run_browser_device_smoke


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a disposable browser tab through the installed Codex browser "
            "plugin, snapshot it, take one screenshot, and close it."
        )
    )
    parser.add_argument("--family", choices=("chrome", "edge"), default="chrome")
    parser.add_argument("--plugin-root", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    adapter = CodexBrowserHelperAdapter(
        family=args.family,
        plugin_root=args.plugin_root,
        session_id="fcc-browser-device-smoke",
    )
    try:
        receipt = run_browser_device_smoke(adapter, family=args.family)
    finally:
        adapter.close()

    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
