"""Server ownership wrappers for the native Rust/Ratatui control center."""

import sys
import tempfile
import threading
from collections.abc import Sequence
from pathlib import Path

from free_claude_code.cli.commands import (
    ServerSupervisor,
    apply_bootstrap_result,
    build_bootstrap_state,
    read_bootstrap_result,
    write_bootstrap_json,
)
from free_claude_code.config.settings import Settings
from free_claude_code.core.branding import PRODUCT_NAME
from free_claude_code.core.server_identity import server_mode

from .control_tui import _format_launch_failure
from .rust_tui import NativeControlCenterUnavailable, run_native_control_center
from .terminal_control import (
    ControlClientLauncher,
    _wait_for_proxy,
)
from .terminal_control import (
    run_attached_control_center as run_legacy_attached_control_center,
)
from .terminal_control import (
    run_owned_control_center as run_legacy_owned_control_center,
)

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

    try:
        run_native_control_center(settings, notice=startup_error)
    except NativeControlCenterUnavailable as exc:
        print(
            f"Native {PRODUCT_NAME} control center unavailable ({exc}); "
            "using the terminal fallback.",
            file=sys.stderr,
        )
        run_legacy_attached_control_center(
            settings,
            launch_client=launch_client,
        )


def run_owned_control_center(
    settings: Settings,
    *,
    launch_client: ControlClientLauncher,
    initial_argv: Sequence[str] | None = None,
    initial_cwd: Path | None = None,
    initial_danger: bool = False,
) -> None:
    """Let the native TUI choose and save state before owning the server.

    The bootstrap phase deliberately has no Uvicorn worker or listening socket.
    Provider model discovery runs against a short-lived in-process runtime,
    then the TUI writes its choices to a private handoff file. Only after that
    file is validated and read back does this function create ServerSupervisor.
    """

    with tempfile.TemporaryDirectory(prefix="fcc-control-bootstrap-") as directory:
        directory_path = Path(directory)
        state_path = directory_path / "state.json"
        result_path = directory_path / "result.json"
        try:
            state = build_bootstrap_state(
                settings,
                launch_after_repository=initial_argv is not None,
                launch_danger=initial_danger,
            )
            write_bootstrap_json(state_path, state)
            run_native_control_center(
                settings,
                bootstrap_state=state_path,
                bootstrap_result=result_path,
            )
            result = read_bootstrap_result(result_path)
            final_settings = apply_bootstrap_result(result)
        except NativeControlCenterUnavailable as exc:
            print(
                f"Native {PRODUCT_NAME} control center unavailable ({exc}); "
                "using the terminal fallback.",
                file=sys.stderr,
            )
            run_legacy_owned_control_center(
                settings,
                launch_client=launch_client,
                initial_argv=initial_argv,
                initial_danger=initial_danger,
            )
            return
        except Exception as exc:
            raise RuntimeError(f"Prelaunch control center failed: {exc}") from exc

    if not result["start_server"]:
        return

    selected_repository = result.get("selected_repository")
    launch_cwd = (
        Path(selected_repository).expanduser()
        if isinstance(selected_repository, str) and selected_repository.strip()
        else initial_cwd
    )

    _run_live_owned_control_center(
        final_settings,
        launch_client=launch_client,
        initial_argv=initial_argv,
        initial_cwd=launch_cwd,
        initial_danger=initial_danger,
    )


def _run_live_owned_control_center(
    settings: Settings,
    *,
    launch_client: ControlClientLauncher,
    initial_argv: Sequence[str] | None = None,
    initial_cwd: Path | None = None,
    initial_danger: bool = False,
) -> None:
    """Own the server worker after prelaunch choices have been committed."""

    supervisor = ServerSupervisor(console_logging=False)
    if not supervisor.schedule_run():
        raise RuntimeError(f"{PRODUCT_NAME} server worker could not be scheduled")
    server_thread = threading.Thread(
        target=supervisor.run, name=f"{PRODUCT_NAME.casefold()}-tui-server"
    )
    server_thread.start()
    startup_error: str | None = None
    try:
        error = _wait_for_proxy(
            settings,
            server_thread,
            supervisor=supervisor,
            expected_mode=server_mode(),
        )
        if error is not None:
            print(
                f"{PRODUCT_NAME} server failed to become ready: {error}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if initial_argv is not None:
            try:
                launch_client(initial_danger, initial_argv, initial_cwd)
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
