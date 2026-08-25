"""Lightweight entry points for installed Free Claude Code commands."""

import os
import socket
import sys
from collections.abc import Sequence

from free_claude_code.core.version import package_version
from free_claude_code.learning.config import (
    PROFILE_ENV,
    LearningProfileError,
    extract_profile_argument,
)

_SERVER_USAGE = "fcc-server [--profile <name>] [--terminal|--no-browser] [--headless]"


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
    _run_server_entrypoint(headless="--headless" in remaining)


def _run_server_entrypoint(*, headless: bool = False) -> None:
    """Run the server after command-line parsing and version short-circuits."""

    # Keep the server composition root off metadata-only command paths.
    from free_claude_code.cli import commands
    from free_claude_code.cli.launchers.common import preflight_proxy
    from free_claude_code.cli.terminal_control import (
        run_attached_control_center,
        run_owned_control_center,
        terminal_control_available,
    )
    from free_claude_code.config.server_urls import local_proxy_root_url

    settings = commands.load_server_settings()
    interactive = not headless and terminal_control_available()
    preflight_error = preflight_proxy(local_proxy_root_url(settings))
    if preflight_error is None:
        if interactive:
            run_attached_control_center(settings)
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
        run_owned_control_center(settings)
        return

    commands.serve()


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
            "Start the local Free Claude Code proxy.\n\n"
            f"Usage: {_SERVER_USAGE}\n\n"
            "Interactive terminals open the FCC terminal control center.\n"
            "--headless keeps the blocking server-only behavior.\n"
            "--terminal and --no-browser remain explicit no-op compatibility flags.\n"
            "FCC never launches a browser automatically."
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


def _server_port_is_occupied(host: str, port: int) -> bool:
    """Detect a listener before Uvicorn can emit a noisy bind traceback."""

    connect_host = host.strip() if host else "127.0.0.1"
    if connect_host in {"0.0.0.0", "::", "[::]"}:
        connect_host = "127.0.0.1"
    connect_host = connect_host.strip("[]")
    try:
        with socket.create_connection((connect_host, port), timeout=0.2):
            return True
    except OSError:
        return False


def _print_version_if_requested(argv: Sequence[str] | None) -> bool:
    args = sys.argv[1:] if argv is None else argv
    if "--version" not in args:
        return False
    print(f"free-claude-code {package_version()}")
    return True
