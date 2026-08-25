"""Installed `fcc-claude` launcher."""

import os
import sys
from collections.abc import Sequence

from free_claude_code.cli.claude_env import (
    CLAUDE_BINARY_NAME,
    build_claude_proxy_env,
    resolved_model_id,
    settings_env_routing_conflict_message,
)
from free_claude_code.cli.claude_firewall import (
    CLAUDE_ALLOW_UNCERTIFIED_ENV,
    CLAUDE_KNOWN_GOOD_VERSION_ENV,
    CLAUDE_PROCESS_WRAPPER_PATH_ENV,
    ClaudeCompatibilityError,
    default_process_wrapper_path,
    enforce_claude_compatibility,
    ensure_process_wrapper,
)
from free_claude_code.config.server_urls import local_proxy_root_url
from free_claude_code.config.settings import get_settings
from free_claude_code.learning.config import (
    PROFILE_ENV,
    LearningProfileError,
    configured_profile,
    extract_profile_argument,
)
from free_claude_code.learning.hooks import ensure_learning_hooks

from .common import preflight_proxy, resolve_client_binary, run_client_process

_DISPLAY_NAME = "Claude Code"
_INSTALL_HINT = "Install Claude Code with: npm install -g @anthropic-ai/claude-code"


def launch(argv: Sequence[str] | None = None) -> None:
    """Launch Claude Code with Free Claude Code proxy environment variables."""

    args = list(sys.argv[1:] if argv is None else argv)
    try:
        args, selected_profile = extract_profile_argument(args)
        configured_profile()
    except LearningProfileError as exc:
        print(f"FCC Learning profile selection failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    if selected_profile is not None:
        os.environ[PROFILE_ENV] = selected_profile

    settings = get_settings()
    proxy_root_url = local_proxy_root_url(settings)
    if error := preflight_proxy(proxy_root_url):
        if _start_interactive_owner(args):
            return
        print(
            f"Free Claude Code proxy is not reachable at {proxy_root_url}: {error}",
            file=sys.stderr,
        )
        print("Start it in another terminal with: fcc-server", file=sys.stderr)
        raise SystemExit(1)

    try:
        ensure_learning_hooks()
    except (OSError, ValueError) as exc:
        print(
            f"FCC Learning hooks were not installed: {type(exc).__name__}",
            file=sys.stderr,
        )

    binary_name = claude_binary_name()
    binary_path = resolve_client_binary(
        binary_name=binary_name,
        display_name=_DISPLAY_NAME,
        install_hint=_INSTALL_HINT,
    )
    if conflict_message := settings_env_routing_conflict_message(
        os.environ,
        cwd=os.getcwd(),
        argv=args,
    ):
        print(conflict_message, file=sys.stderr)
        raise SystemExit(2)
    try:
        firewall_env = _firewall_environment(settings)
        wrapper_path = default_process_wrapper_path(firewall_env)
        if os.path.isfile(binary_path):
            wrapper_path = ensure_process_wrapper(wrapper_path)
            enforce_claude_compatibility(
                binary_path,
                base_env=firewall_env,
                wrapper_path=wrapper_path,
            )
    except ClaudeCompatibilityError as exc:
        print(
            f"FCC Claude compatibility firewall blocked launch: {exc}", file=sys.stderr
        )
        raise SystemExit(78) from None
    run_client_process(
        command=build_claude_launcher_command(binary_path=binary_path, argv=args),
        env=build_claude_proxy_env(
            proxy_root_url=proxy_root_url,
            auth_token=settings.anthropic_auth_token,
            base_env=os.environ,
            model_id=resolved_model_id(args, os.environ),
            process_wrapper_path=str(wrapper_path),
        ),
        binary_name=binary_name,
        display_name=_DISPLAY_NAME,
        install_hint=_INSTALL_HINT,
    )


def _start_interactive_owner(args: Sequence[str]) -> bool:
    """Start an explicit in-process server owner for an interactive direct launch."""

    from free_claude_code.cli import commands
    from free_claude_code.cli.server_startup import server_port_is_occupied
    from free_claude_code.cli.terminal_control import (
        run_owned_control_center,
        terminal_control_available,
    )

    if not terminal_control_available():
        return False

    # The client may have loaded Settings before a legacy env migration. Refresh
    # through the same startup path as fcc-server so the owner and child agree.
    get_settings.cache_clear()
    settings = commands.load_server_settings()
    proxy_root_url = local_proxy_root_url(settings)
    if preflight_proxy(proxy_root_url) is None:
        launch(args)
        return True

    if server_port_is_occupied(settings.host, settings.port):
        print(
            f"FCC cannot start: port {settings.port} is already in use, "
            "but the service on it is not an FCC health endpoint.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print("FCC server is not running; starting the terminal control center.")
    run_owned_control_center(settings, initial_argv=args)
    return True


def _firewall_environment(settings: object) -> dict[str, str]:
    """Overlay validated Settings values onto the inherited launcher env."""

    environment = dict(os.environ)
    known_good = getattr(settings, "claude_known_good_version", "2.1.228")
    if isinstance(known_good, str) and known_good.strip():
        environment[CLAUDE_KNOWN_GOOD_VERSION_ENV] = known_good.strip()
    allow_uncertified = getattr(settings, "claude_allow_uncertified", False)
    environment[CLAUDE_ALLOW_UNCERTIFIED_ENV] = "1" if allow_uncertified else "0"
    wrapper_path = getattr(settings, "claude_process_wrapper_path", "")
    if isinstance(wrapper_path, str) and wrapper_path.strip():
        environment[CLAUDE_PROCESS_WRAPPER_PATH_ENV] = wrapper_path.strip()
    return environment


def launch_danger(argv: Sequence[str] | None = None) -> None:
    """Launch Claude Code with FCC and skip-permissions enabled explicitly."""

    args = list(sys.argv[1:] if argv is None else argv)
    if "--dangerously-skip-permissions" not in args:
        args.insert(0, "--dangerously-skip-permissions")
    launch(args)


def claude_binary_name() -> str:
    """Return the Claude Code binary name."""

    return CLAUDE_BINARY_NAME


def build_claude_launcher_command(
    *, binary_path: str, argv: Sequence[str]
) -> list[str]:
    """Return the Claude wrapper command without changing user arguments."""

    return [binary_path, *argv]
