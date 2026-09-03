"""Lightweight entry points for installed Free Claude Code commands."""

import os
import shutil
import stat
import sys
from collections.abc import Sequence
from pathlib import Path

from free_claude_code.config.paths import (
    FCC_CONFIG_DIR_ENV,
    FCC_ENV_FILENAME,
    config_dir_path,
)
from free_claude_code.core.branding import PRODUCT_NAME
from free_claude_code.core.process_identity import set_process_identity
from free_claude_code.core.server_identity import SERVER_MODE_ENV
from free_claude_code.core.version import package_version
from free_claude_code.learning.config import (
    PROFILE_ENV,
    LearningProfileError,
    extract_profile_argument,
)

_SERVER_USAGE = "fcc-server [--profile <name>] [--terminal|--no-browser] [--headless]"
_FCC_USAGE = "fcc <accounts> [options]"

SANDBOX_CONFIG_DIR_ENV = "FCC_SANDBOX_DIR"
SANDBOX_CONFIG_DIRNAME = ".fcc-sandbox"
SANDBOX_PORT_DEFAULT = 8083
SANDBOX_WEB_TOOLS_ENV = "ENABLE_WEB_SERVER_TOOLS"
SANDBOX_LOCAL_A3S_ENV = "ENABLE_LOCAL_A3S_SEARCH"


def _server_port_is_occupied(host: str, port: int) -> bool:
    """Load the port probe after sandbox environment selection."""

    from free_claude_code.cli.server_startup import server_port_is_occupied

    return server_port_is_occupied(host, port)


def serve(argv: Sequence[str] | None = None) -> None:
    """Start the FastAPI server (registered as ``fcc-server``)."""
    _serve(argv)


def serve_sandbox(argv: Sequence[str] | None = None) -> None:
    """Start an isolated test server (registered as ``t-fcc-server``)."""

    args = tuple(sys.argv[1:] if argv is None else argv)
    _apply_sandbox_defaults()
    if _print_version_if_requested(args):
        return
    if "--help" in args or "-h" in args:
        remaining, _profile = extract_profile_argument(args)
        _parse_server_options(remaining)

    from free_claude_code.cli import commands
    from free_claude_code.config.server_urls import local_admin_url

    settings = commands.load_server_settings()
    print(
        f"{PRODUCT_NAME} sandbox: state in {config_dir_path()} "
        f"({local_admin_url(settings)})"
    )
    _serve(args, process_detail="sandbox")


def _serve(
    argv: Sequence[str] | None = None, *, process_detail: str | None = None
) -> None:
    """Run the shared server entry-point flow with an optional process label."""
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
    set_process_identity("Server", process_detail)
    if "--headless" in remaining:
        _run_server_entrypoint(headless=True)
    else:
        _run_server_entrypoint()


def _apply_sandbox_defaults() -> None:
    """Point this process at sandbox state unless the user set overrides."""

    config_override = os.environ.get(FCC_CONFIG_DIR_ENV, "").strip()
    if config_override:
        sandbox_dir = config_override
    else:
        sandbox_dir = os.environ.get(SANDBOX_CONFIG_DIR_ENV, "").strip()
        if not sandbox_dir:
            sandbox_dir = str(Path.home() / SANDBOX_CONFIG_DIRNAME)
        os.environ[FCC_CONFIG_DIR_ENV] = sandbox_dir
    os.environ.setdefault("PORT", str(SANDBOX_PORT_DEFAULT))
    os.environ.setdefault(SANDBOX_WEB_TOOLS_ENV, "true")
    os.environ.setdefault(SANDBOX_LOCAL_A3S_ENV, "true")
    os.environ[SERVER_MODE_ENV] = "sandbox"
    _seed_sandbox_env(Path(sandbox_dir).expanduser())


def _seed_sandbox_env(sandbox_dir: Path) -> None:
    """Copy the live managed env into the sandbox once, never overwriting."""

    sandbox_env = sandbox_dir / FCC_ENV_FILENAME
    if sandbox_env.exists():
        return
    live_env = Path.home() / ".fcc" / FCC_ENV_FILENAME
    if not live_env.is_file():
        return
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(live_env, sandbox_env)
    sandbox_env.chmod(stat.S_IRUSR | stat.S_IWUSR)


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
    mode = os.environ.get(SERVER_MODE_ENV, "standard").strip() or "standard"
    endpoint = local_proxy_root_url(settings)
    if mode == "sandbox":
        print(
            f"{PRODUCT_NAME} sandbox startup: endpoint {endpoint}; "
            f"state in {config_dir_path()}"
        )
    else:
        print(f"{PRODUCT_NAME} startup: checking {endpoint}")
    preflight_error = preflight_proxy(endpoint, expected_mode=mode)
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
            f"Start the local {PRODUCT_NAME} proxy.\n\n"
            f"Usage: {_SERVER_USAGE}\n\n"
            f"Interactive terminals open the {PRODUCT_NAME} native Ratatui control center.\n"
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
    if args and args[0] in {"accounts", "account", "subs", "subscriptions"}:
        from free_claude_code.cli.codex_accounts import main as run_accounts

        return run_accounts(args[1:])
    if not args or args[0] in {"--help", "-h"}:
        print(f"Usage: {_FCC_USAGE}")
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
    from free_claude_code.cli.launchers.common import ClientLaunchError

    launcher = launch_danger if danger else launch
    try:
        launcher(tuple(argv), cwd=cwd, raise_for_control=True)
    except SystemExit as exc:
        if exc.code in {None, 0}:
            return
        code = exc.code if isinstance(exc.code, int) else 1
        raise ClientLaunchError(
            f"Claude exited with status {exc.code}.",
            code,
        ) from None
