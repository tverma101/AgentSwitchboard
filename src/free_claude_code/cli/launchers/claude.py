"""Installed `fcc-claude` launcher."""

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from free_claude_code.application.session_policy import parse_allowed_helper_ids
from free_claude_code.cli.claude_env import (
    CLAUDE_BINARY_NAME,
    CLAUDE_CONTEXT_CAP_DEFAULT,
    CLAUDE_CONTEXT_CAP_ENV,
    build_claude_proxy_env,
    resolved_model_id,
    settings_env_routing_conflict_message,
)
from free_claude_code.cli.claude_firewall import (
    CLAUDE_ALLOW_UNCERTIFIED_ENV,
    CLAUDE_KNOWN_GOOD_BINARY_ENV,
    CLAUDE_KNOWN_GOOD_VERSION_ENV,
    CLAUDE_PROCESS_WRAPPER_PATH_ENV,
    ClaudeCompatibilityError,
    default_process_wrapper_path,
    enforce_claude_compatibility,
    ensure_process_wrapper,
    find_known_good_claude_binary,
    inspect_claude_compatibility,
    install_known_good_claude_binary,
)
from free_claude_code.cli.codex_computer_use_registration import (
    ClaudeMcpRegistrationError,
    ensure_claude_local_computer_use_mcp,
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
from free_claude_code.runtime.codex_computer_use import (
    CodexComputerUseError,
    resolve_official_computer_use,
)
from free_claude_code.runtime.codex_computer_use_managed import (
    managed_launcher,
)
from free_claude_code.runtime.codex_computer_use_skill import (
    claude_config_dir_from_env,
    install_native_computer_use_skill,
)

from .common import (
    ClientLaunchError,
    preflight_proxy,
    resolve_client_binary,
    run_client_process,
)

_DISPLAY_NAME = "Claude Code"
_INSTALL_HINT = "Install Claude Code with: npm install -g @anthropic-ai/claude-code"
_COMPUTER_USE_HELPER_ID = "codex-computer-use"


def launch(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    raise_for_control: bool = False,
) -> None:
    """Launch Claude Code with Free Claude Code proxy environment variables."""

    args = list(sys.argv[1:] if argv is None else argv)
    try:
        args, selected_profile = extract_profile_argument(args)
        server_profile = configured_profile()
    except LearningProfileError as exc:
        message = f"FCC Learning profile selection failed: {exc}"
        if raise_for_control:
            raise ClientLaunchError(message, 2) from None
        print(message, file=sys.stderr)
        raise SystemExit(2) from None
    launch_profile = selected_profile or server_profile
    launch_environment = dict(os.environ)
    # A launcher invocation is a child-session selection. Never mutate the
    # long-lived FCC server/TUI environment or a later launch can inherit the
    # previous child's profile by accident.
    launch_environment[PROFILE_ENV] = launch_profile

    if _is_help_request(args):
        _run_client_help(args, cwd=cwd, raise_for_control=raise_for_control)
        return

    settings = get_settings()
    # Settings loads the managed FCC env file without mutating os.environ. Copy
    # the validated context-window choice into this child launch only so the TUI
    # setting and direct env override share the existing Claude env policy. Keep
    # the established 256K default for partial/legacy Settings-like callers.
    context_tokens = getattr(
        settings,
        "claude_context_tokens",
        CLAUDE_CONTEXT_CAP_DEFAULT,
    )
    launch_environment[CLAUDE_CONTEXT_CAP_ENV] = str(context_tokens)
    proxy_root_url = local_proxy_root_url(settings)
    if error := preflight_proxy(proxy_root_url):
        started = False
        if not raise_for_control:
            if cwd is None:
                started = (
                    _start_interactive_owner(args)
                    if selected_profile is None
                    else _start_interactive_owner(args, profile=selected_profile)
                )
            else:
                started = (
                    _start_interactive_owner(args, cwd=cwd)
                    if selected_profile is None
                    else _start_interactive_owner(
                        args,
                        cwd=cwd,
                        profile=selected_profile,
                    )
                )
        if started:
            return
        message = (
            f"Free Claude Code proxy is not reachable at {proxy_root_url}: {error}\n"
            "Start it in another terminal with: fcc-server"
        )
        if raise_for_control:
            raise ClientLaunchError(message, 1)
        print(message.splitlines()[0], file=sys.stderr)
        print(message.splitlines()[1], file=sys.stderr)
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
        raise_for_control=raise_for_control,
    )
    if conflict_message := settings_env_routing_conflict_message(
        launch_environment,
        cwd=str(cwd) if cwd is not None else os.getcwd(),
        argv=args,
    ):
        if raise_for_control:
            raise ClientLaunchError(conflict_message, 2)
        print(conflict_message, file=sys.stderr)
        raise SystemExit(2)
    firewall_env = _firewall_environment(settings, base_env=launch_environment)
    wrapper_path = default_process_wrapper_path(firewall_env)
    compatibility_error: ClaudeCompatibilityError | None = None
    fallback_version: str | None = None
    recovered_from: str | None = None
    try:
        if os.path.isfile(binary_path):
            wrapper_path = ensure_process_wrapper(wrapper_path)
            enforce_claude_compatibility(
                binary_path,
                base_env=firewall_env,
                wrapper_path=wrapper_path,
            )
    except ClaudeCompatibilityError as exc:
        fallback_path, fallback_version = _recover_known_good_binary(
            binary_path,
            base_env=firewall_env,
            wrapper_path=wrapper_path,
        )
        if fallback_path is None:
            compatibility_error = ClaudeCompatibilityError(
                f"{exc}\n{_known_good_recovery_hint(fallback_version)}"
                if fallback_version is not None
                else str(exc)
            )
        else:
            try:
                enforce_claude_compatibility(
                    fallback_path,
                    base_env=firewall_env,
                    wrapper_path=wrapper_path,
                )
            except ClaudeCompatibilityError as fallback_exc:
                compatibility_error = ClaudeCompatibilityError(
                    f"{fallback_exc}\n{_known_good_recovery_hint(fallback_version)}"
                )
            else:
                recovered_from = binary_path
                binary_path = fallback_path

    if compatibility_error is not None:
        message = (
            f"FCC Claude compatibility firewall blocked launch: {compatibility_error}"
        )
        if raise_for_control:
            raise ClientLaunchError(message, 78) from None
        print(
            message,
            file=sys.stderr,
        )
        raise SystemExit(78) from None
    if recovered_from is not None and not raise_for_control:
        recovered_version = fallback_version or "the known-good version"
        print(
            f"FCC: the installed Claude executable was quarantined; "
            f"starting the verified {recovered_version} fallback.",
            file=sys.stderr,
        )
    child_env = build_claude_proxy_env(
        proxy_root_url=proxy_root_url,
        auth_token=settings.anthropic_auth_token,
        base_env=launch_environment,
        model_id=resolved_model_id(args, launch_environment),
        process_wrapper_path=str(wrapper_path),
    )
    _prepare_computer_use_session(
        settings,
        claude_binary=binary_path,
        cwd=cwd,
        base_env=child_env,
        raise_for_control=raise_for_control,
    )
    run_client_process(
        command=build_claude_launcher_command(binary_path=binary_path, argv=args),
        env=child_env,
        binary_name=binary_name,
        display_name=_DISPLAY_NAME,
        install_hint=_INSTALL_HINT,
        cwd=cwd,
        raise_for_control=raise_for_control,
    )


def _computer_use_is_enabled(settings: object) -> bool:
    """Return whether the signed Computer Use helper was explicitly enabled."""

    allowed = getattr(settings, "allowed_helper_ids", "")
    return isinstance(allowed, str) and _COMPUTER_USE_HELPER_ID in set(
        parse_allowed_helper_ids(allowed)
    )


def _is_help_request(args: Sequence[str]) -> bool:
    """Return whether the client invocation is a side-effect-free help query."""

    return any(argument in {"--help", "-h"} for argument in args)


def _run_client_help(
    args: Sequence[str],
    *,
    cwd: Path | None,
    raise_for_control: bool,
) -> None:
    """Delegate help to Claude without starting FCC or mutating its config."""

    binary_path = resolve_client_binary(
        binary_name=claude_binary_name(),
        display_name=_DISPLAY_NAME,
        install_hint=_INSTALL_HINT,
        raise_for_control=raise_for_control,
    )
    run_client_process(
        command=[binary_path, *args],
        env=dict(os.environ),
        binary_name=claude_binary_name(),
        display_name=_DISPLAY_NAME,
        install_hint=_INSTALL_HINT,
        cwd=cwd,
        raise_for_control=raise_for_control,
    )


def _prepare_computer_use_session(
    settings: object,
    *,
    claude_binary: str,
    cwd: Path | None,
    base_env: dict[str, str],
    raise_for_control: bool,
) -> None:
    """Expose the official skill and executable MCP server before Claude starts.

    The native broker remains lazy: this startup step only validates the signed
    installation, installs the source-owned skill link, and registers the fixed
    app-server-backed local MCP command. No screenshot or native Computer Use
    action is started.
    """

    if not _computer_use_is_enabled(settings):
        return

    session_cwd = (cwd or Path.cwd()).expanduser().resolve()
    claude_config_dir = claude_config_dir_from_env(base_env)
    home = Path(base_env.get("HOME", str(Path.home()))).expanduser()
    approval_mode = getattr(settings, "computer_use_approval", "auto")
    if isinstance(approval_mode, str):
        base_env["FCC_COMPUTER_USE_APPROVAL"] = approval_mode
    try:
        paths = resolve_official_computer_use(home=home)
        install_native_computer_use_skill(
            paths,
            claude_config_dir=claude_config_dir,
        )
        managed = managed_launcher(paths)
        bundled_launcher = managed[1] if managed is not None else None
        old_profile_launcher = (
            claude_config_dir
            / "fcc/codex-computer-use/bin/computer-use-client-launcher"
        )
        ensure_claude_local_computer_use_mcp(
            claude_binary=claude_binary,
            cwd=session_cwd,
            base_env=base_env,
            node_executable=None,
            bridge_path=None,
            python_executable=sys.executable,
            native_launcher=old_profile_launcher,
            legacy_native_launcher=bundled_launcher,
        )
    except (ClaudeMcpRegistrationError, CodexComputerUseError, OSError) as exc:
        message = _computer_use_setup_error(
            exc,
            claude_config_dir=claude_config_dir,
            session_cwd=session_cwd,
        )
        if raise_for_control:
            raise ClientLaunchError(message, 78) from None
        print(message, file=sys.stderr)
        raise SystemExit(78) from None


def _computer_use_setup_error(
    error: Exception,
    *,
    claude_config_dir: Path,
    session_cwd: Path,
) -> str:
    """Return an actionable error instead of exposing only an exit status."""

    return (
        "FCC Computer Use could not be enabled for this Claude session.\n"
        f"Reason: {error}\n"
        f"Project: {session_cwd}\n"
        f"Claude config: {claude_config_dir}\n"
        "The signed Codex Computer Use installation must be available, and "
        "FCC_ALLOWED_HELPERS must include codex-computer-use. Restart fcc-server "
        "after repairing the installation or policy, then try again."
    )


def _recover_known_good_binary(
    binary_path: str,
    *,
    base_env: dict[str, str],
    wrapper_path: Path,
) -> tuple[str | None, str | None]:
    """Return an exact known-good fallback after a version quarantine.

    Recovery is intentionally limited to a quarantined Claude 2.x binary
    whose major/minor train matches the configured known-good version.  This
    avoids interpreting an unrelated executable's ``--version`` output as a
    Claude release, while still recovering normal Claude patch upgrades.
    """

    status = inspect_claude_compatibility(
        binary_path,
        base_env=base_env,
        wrapper_path=wrapper_path,
    )
    if status.state != "quarantined" or status.version is None:
        return None, None
    if status.version == status.known_good_version:
        return None, None
    if status.version.split(".")[:2] != status.known_good_version.split(".")[:2]:
        return None, None

    fallback = find_known_good_claude_binary(
        binary_path,
        base_env=base_env,
        known_good_version=status.known_good_version,
    )
    if fallback is None:
        fallback = install_known_good_claude_binary(
            base_env=base_env,
            known_good_version=status.known_good_version,
        )
    return fallback, status.known_good_version


def _known_good_recovery_hint(version: str | None) -> str:
    """Explain the next repair action when no exact local fallback exists."""

    if version is None:
        return "FCC could not identify a recoverable Claude version."
    return (
        f"FCC checked PATH and its private offline cache but found no runnable "
        f"Claude Code {version}. Install the exact version with `npm install -g "
        f"@anthropic-ai/claude-code@{version}` or set "
        f"{CLAUDE_KNOWN_GOOD_BINARY_ENV} to an existing {version} executable, "
        "then choose Repair & start again. Do not set "
        f"{CLAUDE_ALLOW_UNCERTIFIED_ENV}=1 unless you intentionally want a "
        "bounded canary."
    )


def _start_interactive_owner(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    profile: str | None = None,
) -> bool:
    """Start an explicit in-process server owner for an interactive direct launch."""

    from free_claude_code.cli import commands
    from free_claude_code.cli.control_tui_entry import run_owned_control_center
    from free_claude_code.cli.server_startup import server_port_is_occupied
    from free_claude_code.cli.terminal_control import terminal_control_available

    if not terminal_control_available():
        return False

    # The client may have loaded Settings before a legacy env migration. Refresh
    # through the same startup path as fcc-server so the owner and child agree.
    get_settings.cache_clear()
    settings = commands.load_server_settings()
    proxy_root_url = local_proxy_root_url(settings)
    initial_argv = tuple(args)
    if profile is not None:
        initial_argv = ("--profile", profile, *initial_argv)
    if preflight_proxy(proxy_root_url) is None:
        if cwd is None:
            launch(initial_argv)
        else:
            launch(initial_argv, cwd=cwd)
        return True

    if server_port_is_occupied(settings.host, settings.port):
        print(
            f"FCC cannot start: port {settings.port} is already in use, "
            "but the service on it is not an FCC health endpoint.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print("FCC server is not running; starting the terminal control center.")
    run_owned_control_center(
        settings,
        initial_argv=initial_argv,
        initial_cwd=cwd,
        initial_danger="--dangerously-skip-permissions" in initial_argv,
        launch_client=_launch_control_client,
    )
    return True


def _launch_control_client(
    danger: bool, argv: Sequence[str], cwd: Path | None = None
) -> None:
    """Launch a Claude client selected by the terminal control callback."""

    launcher = launch_danger if danger else launch
    try:
        if cwd is None:
            launcher(tuple(argv), raise_for_control=True)
        else:
            launcher(tuple(argv), cwd=cwd, raise_for_control=True)
    except SystemExit as exc:
        if exc.code in {None, 0}:
            return
        code = exc.code if isinstance(exc.code, int) else 1
        raise ClientLaunchError(
            f"Claude exited with status {exc.code}.",
            code,
        ) from None


def _firewall_environment(
    settings: object,
    *,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Overlay validated Settings values onto the inherited launcher env."""

    environment = dict(os.environ if base_env is None else base_env)
    known_good = getattr(settings, "claude_known_good_version", "2.1.228")
    if isinstance(known_good, str) and known_good.strip():
        environment[CLAUDE_KNOWN_GOOD_VERSION_ENV] = known_good.strip()
    known_good_binary = getattr(settings, "claude_known_good_binary", "")
    if isinstance(known_good_binary, str) and known_good_binary.strip():
        environment[CLAUDE_KNOWN_GOOD_BINARY_ENV] = known_good_binary.strip()
    allow_uncertified = getattr(settings, "claude_allow_uncertified", False)
    environment[CLAUDE_ALLOW_UNCERTIFIED_ENV] = "1" if allow_uncertified else "0"
    wrapper_path = getattr(settings, "claude_process_wrapper_path", "")
    if isinstance(wrapper_path, str) and wrapper_path.strip():
        environment[CLAUDE_PROCESS_WRAPPER_PATH_ENV] = wrapper_path.strip()
    return environment


def launch_danger(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    raise_for_control: bool = False,
) -> None:
    """Launch Claude Code with FCC and skip-permissions enabled explicitly."""

    args = list(sys.argv[1:] if argv is None else argv)
    if "--dangerously-skip-permissions" not in args:
        args.insert(0, "--dangerously-skip-permissions")
    if raise_for_control:
        launch(args, cwd=cwd, raise_for_control=True)
    else:
        launch(args, cwd=cwd)


def claude_binary_name() -> str:
    """Return the Claude Code binary name."""

    return CLAUDE_BINARY_NAME


def build_claude_launcher_command(
    *, binary_path: str, argv: Sequence[str]
) -> list[str]:
    """Return the Claude wrapper command without changing user arguments."""

    return [binary_path, *argv]
