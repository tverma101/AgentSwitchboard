"""Server ownership wrappers for the native Rust/Ratatui control center."""

import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from free_claude_code.cli.commands import ServerSupervisor
from free_claude_code.config.settings import Settings

from .control_tui import _format_launch_failure
from .rust_tui import run_native_control_center
from .terminal_control import _wait_for_proxy

ControlClientLauncher = Callable[[bool, Sequence[str], Path | None], None]
TUI_SHUTDOWN_TIMEOUT_SECONDS = 5.0


def run_control_tui(
    settings: Settings,
    *,
    supervisor: ServerSupervisor | None,
    launch_client: ControlClientLauncher,
    startup_error: str | None = None,
) -> None:
    """Compatibility seam that now runs the native control center.

    The old Textual entry point was public to launchers and downstream
    integrations. Keep its call shape while making the Rust/Ratatui client
    the only foreground implementation.
    """

    del supervisor, launch_client
    run_native_control_center(settings, notice=startup_error)


def run_owned_control_center(
    settings: Settings,
    *,
    launch_client: ControlClientLauncher,
    initial_argv: Sequence[str] | None = None,
) -> None:
    """Own the server worker while the native control center is foreground."""

    supervisor = ServerSupervisor(console_logging=False)
    if not supervisor.schedule_run():
        raise RuntimeError("CodeSwitchyard server worker could not be scheduled")
    server_thread = threading.Thread(
        target=supervisor.run, name="codeswitchyard-tui-server"
    )
    server_thread.start()
    startup_error: str | None = None
    try:
        error = _wait_for_proxy(settings, server_thread)
        if error is not None:
            print(
                f"CodeSwitchyard server failed to become ready: {error}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if initial_argv is not None:
            try:
                launch_client(False, initial_argv, None)
            except SystemExit as exc:
                startup_error = _format_launch_failure(exc)
            except Exception as exc:
                startup_error = _format_launch_failure(exc)
        run_control_tui(
            settings,
            supervisor=supervisor,
            launch_client=launch_client,
            startup_error=startup_error,
        )
    finally:
        supervisor.request_stop()
        server_thread.join(TUI_SHUTDOWN_TIMEOUT_SECONDS)
        if server_thread.is_alive() is True:
            print(
                "CodeSwitchyard server worker did not stop within "
                f"{TUI_SHUTDOWN_TIMEOUT_SECONDS:g}s.",
                file=sys.stderr,
            )


def run_attached_control_center(
    settings: Settings,
    *,
    launch_client: ControlClientLauncher,
) -> None:
    """Attach the native control center to a server owned by another process."""

    run_control_tui(
        settings,
        supervisor=None,
        launch_client=launch_client,
    )
