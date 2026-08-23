"""Command-line entrypoint for FCC Learning."""

import argparse
import json
import sys

from .hooks import install_hooks, run_hook, uninstall_hooks
from .store import LearningStore, learning_home


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fcc-learning",
        description="Persistent memory and automatic Claude Code skill learning for FCC.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("install", help="merge FCC Learning hooks into Claude Code")
    subcommands.add_parser("uninstall", help="remove only FCC Learning hooks")
    subcommands.add_parser("status", help="show local learning state")

    hook = subcommands.add_parser("hook", help=argparse.SUPPRESS)
    hook.add_argument("event", choices=("session-start", "user-prompt"))
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "install":
        changed = install_hooks()
        print("installed" if changed else "already installed")
        return
    if args.command == "uninstall":
        changed = uninstall_hooks()
        print("removed" if changed else "not installed")
        return
    if args.command == "status":
        store = LearningStore()
        print(json.dumps({"home": str(learning_home()), **store.counts()}, indent=2))
        return
    if args.command == "hook":
        try:
            run_hook(args.event)
        except Exception as exc:
            print(f"FCC Learning hook failed: {type(exc).__name__}", file=sys.stderr)
        return


if __name__ == "__main__":
    main()
