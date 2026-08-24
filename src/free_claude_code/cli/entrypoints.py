"""Lightweight entry points for installed Free Claude Code commands."""

import socket
import sys
from collections.abc import Sequence

from free_claude_code.core.version import package_version

_SERVER_USAGE = "fcc-server [--terminal|--no-browser]"


def serve(argv: Sequence[str] | None = None) -> None:
    """Start the FastAPI server (registered as ``fcc-server``)."""
    args = tuple(sys.argv[1:] if argv is None else argv)
    if _print_version_if_requested(args):
        return
    _parse_server_options(args)
    _run_server_entrypoint()


def _run_server_entrypoint() -> None:
    """Run the server after command-line parsing and version short-circuits."""

    # Keep the server composition root off metadata-only command paths.
    from free_claude_code.cli import commands
    from free_claude_code.cli.launchers.common import preflight_proxy
    from free_claude_code.config.server_urls import local_proxy_root_url

    settings = commands.load_server_settings()
    preflight_error = preflight_proxy(local_proxy_root_url(settings))
    if preflight_error is None:
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

    commands.serve()


def _parse_server_options(args: Sequence[str]) -> bool | None:
    """Parse the small, side-effect-free option surface of ``fcc-server``."""

    allowed = {"--help", "-h", "--terminal", "--no-browser"}
    unknown = [arg for arg in args if arg not in allowed]
    if unknown:
        print(f"Usage: {_SERVER_USAGE}", file=sys.stderr)
        print(f"fcc-server: unrecognized argument: {unknown[0]}", file=sys.stderr)
        raise SystemExit(2)
    if "--help" in args or "-h" in args:
        print(
            "Start the local Free Claude Code proxy.\n\n"
            f"Usage: {_SERVER_USAGE}\n\n"
            "This personal fork is terminal-only: FCC never launches a browser.\n"
            "--terminal and --no-browser are accepted as explicit no-op\n"
            "compatibility flags."
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
