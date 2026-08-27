"""Lightweight entry points for installed Free Claude Code commands."""

import os
import sys
from collections.abc import Sequence
from pathlib import Path

from free_claude_code.cli.server_startup import (
    server_port_is_occupied as _server_port_is_occupied,
)
from free_claude_code.core.process_identity import set_process_identity
from free_claude_code.core.version import package_version
from free_claude_code.learning.config import (
    PROFILE_ENV,
    LearningProfileError,
    extract_profile_argument,
)

_SERVER_USAGE = "fcc-server [--profile <name>] [--terminal|--no-browser] [--headless]"
_FCC_USAGE = "fcc <burst|accounts> [options]"


def serve(argv: Sequence[str] | None = None) -> None:
    """Start the FastAPI server (registered as ``fcc-server``)."""
    args = tuple(sys.argv[1:] if argv is None else argv)
    if _print_version_if_requested(args):
        return
    try:
        remaining, profile = extract_profile_argument(args)
    except LearningProfileError as exc:
        print(f"fcc-server: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    if profile is not None:
        os.environ[PROFILE_ENV] = profile
    _parse_server_options(remaining)
    set_process_identity("Server")
    if "--headless" in remaining:
        _run_server_entrypoint(headless=True)
    else:
        _run_server_entrypoint()


def _run_server_entrypoint(*, headless: bool = False) -> None:
    """Run the server after command-line parsing and version short-circuits."""

    # Keep the server composition root off metadata-only command paths.
    from free_claude_code.cli import commands
    from free_claude_code.cli.control_tui_entry import (
        run_attached_control_center,
        run_owned_control_center,
    )
    from free_claude_code.cli.launchers.common import preflight_proxy
    from free_claude_code.cli.terminal_control import terminal_control_available
    from free_claude_code.config.server_urls import local_proxy_root_url

    settings = commands.load_server_settings()
    interactive = not headless and terminal_control_available()
    preflight_error = preflight_proxy(local_proxy_root_url(settings))
    if preflight_error is None:
        if interactive:
            run_attached_control_center(
                settings,
                launch_client=_launch_claude_from_control,
            )
        else:
            print(
                "FCC server is already running at "
                f"{local_proxy_root_url(settings)}; terminal-only mode is active."
            )
        return

    if _server_port_is_occupied(settings.host, settings.port):
        print(
            f"FCC cannot start: port {settings.port} is already in use, "
            "but the service on it is not an FCC health endpoint. "
            "Set PORT to another free port or stop that service.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if interactive:
        run_owned_control_center(
            settings,
            launch_client=_launch_claude_from_control,
        )
        return

    commands.serve()


def _launch_control_claude(*, danger: bool, argv: Sequence[str] = ()) -> None:
    """Adapt the installed Claude launcher to the terminal-control callback."""

    from free_claude_code.cli.launchers.claude import launch, launch_danger

    launcher = launch_danger if danger else launch
    try:
        launcher(tuple(argv))
    except SystemExit as exc:
        if exc.code not in {None, 0}:
            print(f"Claude exited with status {exc.code}.")


def _parse_server_options(args: Sequence[str]) -> bool | None:
    """Parse the small, side-effect-free option surface of ``fcc-server``."""

    allowed = {"--help", "-h", "--terminal", "--no-browser", "--headless"}
    unknown = [arg for arg in args if arg not in allowed]
    if unknown:
        print(f"Usage: {_SERVER_USAGE}", file=sys.stderr)
        print(f"fcc-server: unrecognized argument: {unknown[0]}", file=sys.stderr)
        raise SystemExit(2)
    if "--help" in args or "-h" in args:
        print(
            "Start the local CodeSwitchyard proxy.\n\n"
            f"Usage: {_SERVER_USAGE}\n\n"
            "Interactive terminals open the CodeSwitchyard Textual control center.\n"
            "--headless keeps the blocking server-only behavior.\n"
            "--terminal and --no-browser remain explicit no-op compatibility flags.\n"
            "Authentication browsers open only after an explicit login action."
        )
        raise SystemExit(0)

    choices = [arg for arg in args if arg in {"--terminal", "--no-browser"}]
    if len(choices) > 1:
        print(
            "fcc-server: choose only one of --terminal or --no-browser",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return None


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
    if args and args[0] in {"accounts", "account", "subs", "subscriptions"}:
        from free_claude_code.cli.codex_accounts import main as run_accounts

        return run_accounts(args[1:])
    if not args or args[0] in {"--help", "-h"}:
        print(f"Usage: {_FCC_USAGE}")
        print("  fcc burst ...      opt-in CI burst runner")
        print("  fcc accounts       manage ChatGPT/Codex subscription accounts")
        return 0
    if args[0] == "--version":
        print(f"free-claude-code {package_version()}")
        return 0
    print(f"fcc: unknown command {args[0]}", file=sys.stderr)
    print(f"Usage: {_FCC_USAGE}", file=sys.stderr)
    return 2


def _print_version_if_requested(argv: Sequence[str] | None) -> bool:
    args = sys.argv[1:] if argv is None else argv
    if "--version" not in args:
        return False
    print(f"free-claude-code {package_version()}")
    return True


def _launch_claude_from_control(
    danger: bool, argv: Sequence[str], cwd: Path | None = None
) -> None:
    """Adapt the terminal client callback to the Claude launcher entry points."""

    from free_claude_code.cli.launchers.claude import launch, launch_danger

    launcher = launch_danger if danger else launch
    try:
        launcher(tuple(argv), cwd=cwd)
    except SystemExit as exc:
        if exc.code not in {None, 0}:
            print(f"Claude exited with status {exc.code}.")
