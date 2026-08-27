"""Lightweight entry points for installed Free Claude Code commands."""

import sys
from collections.abc import Sequence

from free_claude_code.core.version import package_version


def serve(argv: Sequence[str] | None = None) -> None:
    """Start the FastAPI server (registered as ``fcc-server``)."""
    if _print_version_if_requested(argv):
        return

    # Keep the server composition root off metadata-only command paths.
    from free_claude_code.cli.commands import serve as run_server

    run_server()


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch the top-level ``fcc`` command."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "burst":
        from free_claude_code.cli.burst import main as run_burst

        try:
            return run_burst(args[1:])
        except RuntimeError as exc:
            print(f"fcc burst: {exc}", file=sys.stderr)
            return 1
    if not args or args[0] in {"--help", "-h"}:
        print("Usage: fcc burst [options]")
        return 0
    if args[0] == "--version":
        print(f"free-claude-code {package_version()}")
        return 0
    print(f"fcc: unknown command {args[0]}", file=sys.stderr)
    print("Usage: fcc burst [options]", file=sys.stderr)
    return 2


def _print_version_if_requested(argv: Sequence[str] | None) -> bool:
    args = sys.argv[1:] if argv is None else argv
    if "--version" not in args:
        return False
    print(f"free-claude-code {package_version()}")
    return True
