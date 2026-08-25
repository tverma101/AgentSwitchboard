"""Small terminal control surface over the canonical FCC server lifecycle."""

import json
import os
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from free_claude_code.cli.claude_env import context_cap_tokens
from free_claude_code.cli.commands import ServerStatus, ServerSupervisor
from free_claude_code.cli.launchers.common import preflight_proxy
from free_claude_code.config.paths import managed_env_path, server_log_path
from free_claude_code.config.server_urls import local_proxy_root_url
from free_claude_code.config.settings import Settings
from free_claude_code.learning.config import configured_profile

CONTROL_STARTUP_TIMEOUT_SECONDS = 30.0
LOG_PREVIEW_LINES = 30


def terminal_control_available(
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> bool:
    """Return whether an interactive terminal control surface is appropriate."""

    stdin = sys.stdin if input_stream is None else input_stream
    stdout = sys.stdout if output_stream is None else output_stream
    return stdin.isatty() and stdout.isatty()


def run_owned_control_center(
    settings: Settings,
    *,
    initial_argv: Sequence[str] | None = None,
) -> None:
    """Own one FCC server worker while the terminal menu stays in foreground."""

    supervisor = ServerSupervisor(console_logging=False)
    if not supervisor.schedule_run():
        raise RuntimeError("FCC server worker could not be scheduled")

    server_thread = threading.Thread(
        target=supervisor.run,
        name="fcc-terminal-server",
    )
    server_thread.start()
    try:
        error = _wait_for_proxy(settings, server_thread)
        if error is not None:
            print(f"FCC server failed to become ready: {error}", file=sys.stderr)
            raise SystemExit(1)
        if initial_argv is not None:
            _launch_claude(danger=False, argv=initial_argv)
        run_control_menu(settings, supervisor=supervisor)
    finally:
        supervisor.request_stop()
        server_thread.join()


def run_attached_control_center(settings: Settings) -> None:
    """Use the terminal menu with an FCC server owned by another process."""

    run_control_menu(settings, supervisor=None)


def run_control_menu(
    settings: Settings,
    *,
    supervisor: ServerSupervisor | None,
) -> None:
    """Run the intentionally small line-oriented FCC terminal menu."""

    while True:
        _print_home(settings, supervisor=supervisor)
        try:
            choice = input("FCC> ").strip().casefold()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if choice in {"", "c", "claude"}:
            _launch_claude(danger=False)
        elif choice in {"d", "danger"}:
            _launch_claude(danger=True)
        elif choice in {"s", "settings"}:
            _print_settings(settings)
        elif choice in {"l", "logs"}:
            _print_logs(server_log_path())
        elif choice in {"r", "restart"}:
            if supervisor is None:
                print("Server is owned by another process; restart is unavailable here.")
            elif supervisor.request_restart():
                print("FCC server restart requested.")
            else:
                print("FCC server is not in a restartable state.")
        elif choice in {"q", "quit", "exit"}:
            return
        else:
            print("Unknown command. Use Enter/C, D, S, L, R, or Q.")


def _print_home(
    settings: Settings,
    *,
    supervisor: ServerSupervisor | None,
) -> None:
    owner = "this terminal" if supervisor is not None else "another process"
    status = (
        supervisor.status.value
        if supervisor is not None
        else ServerStatus.RUNNING.value
    )
    print()
    print("FCC Harness")
    print("-----------")
    print(f"Server    {status} ({owner})")
    print(f"Model     {settings.model}")
    print(f"Profile   {configured_profile()}")
    print(f"Context   {context_cap_tokens(os.environ):,} tokens")
    print()
    print("[Enter/C] Claude   [D] Danger   [S] Settings   [L] Logs")
    print("[R] Restart        [Q] Quit")


def _print_settings(settings: Settings) -> None:
    print()
    print("Settings")
    print("--------")
    print(f"Managed config  {managed_env_path()}")
    print(f"Model           {settings.model}")
    print(f"Reasoning       {settings.reasoning_policy.value}")
    print(f"Profile         {configured_profile()}")
    print(f"Context         {context_cap_tokens(os.environ):,} tokens")
    print(f"Server          {local_proxy_root_url(settings)}")
    print("Config editing will use the canonical Admin apply/validate path in the next slice.")


def _print_logs(path: Path, *, limit: int = LOG_PREVIEW_LINES) -> None:
    print()
    print(f"Server logs — {path}")
    print("-----------")
    for line in _tail_lines(path, limit=limit):
        print(_render_log_line(line))


def _tail_lines(path: Path, *, limit: int) -> tuple[str, ...]:
    if limit <= 0:
        return ()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return (f"Log unavailable ({type(exc).__name__}).",)
    return tuple(lines[-limit:])


def _render_log_line(line: str) -> str:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return line
    if not isinstance(payload, dict):
        return line
    timestamp = str(payload.get("time", ""))
    if "T" in timestamp:
        timestamp = timestamp.split("T", 1)[1][:8]
    level = str(payload.get("level", "INFO"))
    message = str(payload.get("message", ""))
    return f"{timestamp:>8} {level:<8} {message}".rstrip()


def _launch_claude(
    *,
    danger: bool,
    argv: Sequence[str] = (),
) -> None:
    from free_claude_code.cli.launchers.claude import launch, launch_danger

    launcher = launch_danger if danger else launch
    try:
        launcher(tuple(argv))
    except SystemExit as exc:
        if exc.code not in {None, 0}:
            print(f"Claude exited with status {exc.code}.")


def _wait_for_proxy(
    settings: Settings,
    server_thread: threading.Thread,
    *,
    timeout: float = CONTROL_STARTUP_TIMEOUT_SECONDS,
) -> str | None:
    proxy_root_url = local_proxy_root_url(settings)
    deadline = time.monotonic() + timeout
    last_error = "server did not report healthy"
    while time.monotonic() < deadline:
        error = preflight_proxy(proxy_root_url)
        if error is None:
            return None
        last_error = error
        if not server_thread.is_alive():
            return f"server worker exited before health succeeded ({last_error})"
        time.sleep(0.1)
    return f"health check timed out ({last_error})"
