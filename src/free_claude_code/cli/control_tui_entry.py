"""Server ownership wrappers for the native Rust/Ratatui control center."""

import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from free_claude_code.cli.commands import ServerSupervisor
from free_claude_code.config.settings import Settings
from free_claude_code.core.branding import PRODUCT_NAME

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
    launch_args: Sequence[str] = (),
    launch_cwd: Path | None = None,
    launch_danger: bool = False,
) -> None:
    """Compatibility seam that now runs the native control center.

    The old Textual entry point was public to launchers and downstream
    integrations. Keep its call shape while making the Rust/Ratatui client
    the only foreground implementation.
    """

    del supervisor, launch_client
    run_native_control_center(
        settings,
        notice=startup_error,
        launch_args=launch_args,
        launch_cwd=launch_cwd,
        launch_danger=launch_danger,
    )


def run_owned_control_center(
    settings: Settings,
    *,
    launch_client: ControlClientLauncher,
    initial_argv: Sequence[str] | None = None,
    initial_cwd: Path | None = None,
    initial_danger: bool = False,
) -> None:
    """Own the server while the native control center is foreground.

    Direct ``fcc`` launches carry their requested client arguments into the
    TUI as pending launch context. The user chooses Normal or Danger after the
    server is ready; the client is never launched behind the TUI before its
    model/repository controls are available.
    """

    supervisor = ServerSupervisor(console_logging=False)
    if not supervisor.schedule_run():
        raise RuntimeError(f"{PRODUCT_NAME} server worker could not be scheduled")
    server_thread = threading.Thread(
        target=supervisor.run, name=f"{PRODUCT_NAME.casefold()}-tui-server"
    )
    server_thread.start()
    try:
        error = _wait_for_proxy(settings, server_thread)
        if error is not None:
            print(
                f"{PRODUCT_NAME} server failed to become ready: {error}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        run_control_tui(
            settings,
            supervisor=supervisor,
            launch_client=launch_client,
            launch_args=tuple(initial_argv or ()),
            launch_cwd=initial_cwd,
            launch_danger=initial_danger,
        )
    finally:
        supervisor.request_stop()
        server_thread.join(TUI_SHUTDOWN_TIMEOUT_SECONDS)
        if server_thread.is_alive() is True:
            print(
                f"{PRODUCT_NAME} server worker did not stop within "
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
