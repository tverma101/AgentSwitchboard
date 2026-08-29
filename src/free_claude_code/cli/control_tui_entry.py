"""Server ownership wrappers for the Harlequin-derived Textual control center."""

import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from free_claude_code.cli.commands import ServerSupervisor
from free_claude_code.config.settings import Settings

from .control_tui import _format_launch_failure, run_control_tui
from .terminal_control import _wait_for_proxy

ControlClientLauncher = Callable[[bool, Sequence[str], Path | None], None]


def run_owned_control_center(
    settings: Settings,
    *,
    launch_client: ControlClientLauncher,
    initial_argv: Sequence[str] | None = None,
) -> None:
    """Own the server worker while the Textual application is foreground."""

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
        server_thread.join()


def run_attached_control_center(
    settings: Settings,
    *,
    launch_client: ControlClientLauncher,
) -> None:
    """Attach the Textual application to a server owned by another process."""

    run_control_tui(
        settings,
        supervisor=None,
        launch_client=launch_client,
    )
