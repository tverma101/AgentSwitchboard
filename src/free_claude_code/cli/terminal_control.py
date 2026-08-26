"""Small terminal control surface over the canonical FCC server lifecycle."""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from free_claude_code.cli.claude_env import context_cap_tokens
from free_claude_code.cli.commands import ServerStatus, ServerSupervisor
from free_claude_code.cli.launchers.common import preflight_proxy
from free_claude_code.cli.local_admin import (
    LocalAdminError,
    apply_admin_values,
    get_admin_config,
    get_admin_status,
)
from free_claude_code.config.paths import managed_env_path, server_log_path
from free_claude_code.config.server_urls import local_proxy_root_url
from free_claude_code.config.settings import Settings
from free_claude_code.learning.config import configured_profile

CONTROL_STARTUP_TIMEOUT_SECONDS = 30.0
CODEX_STATUS_TIMEOUT_SECONDS = 5.0
LOG_PREVIEW_LINES = 30
_CODEX_API_ENV_KEYS = ("OPENAI_API_KEY", "CODEX_API_KEY")
ClaudeLauncher = Callable[[bool, Sequence[str]], None]


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
    launch_claude: ClaudeLauncher,
) -> None:
    """Own one FCC server worker while the terminal menu stays in foreground."""

    supervisor = ServerSupervisor(console_logging=False)
    if not supervisor.schedule_run():
        raise RuntimeError("FCC server worker could not be scheduled")

    server_thread = threading.Thread(target=supervisor.run, name="fcc-terminal-server")
    server_thread.start()
    try:
        error = _wait_for_proxy(settings, server_thread)
        if error is not None:
            print(f"FCC server failed to become ready: {error}", file=sys.stderr)
            raise SystemExit(1)
        if initial_argv is not None:
            launch_claude(False, initial_argv)
        run_control_menu(
            settings,
            supervisor=supervisor,
            launch_claude=launch_claude,
        )
    finally:
        supervisor.request_stop()
        server_thread.join()


def run_attached_control_center(
    settings: Settings,
    *,
    launch_claude: ClaudeLauncher,
) -> None:
    """Use the terminal menu with an FCC server owned by another process."""

    run_control_menu(settings, supervisor=None, launch_claude=launch_claude)


def run_control_menu(
    settings: Settings,
    *,
    supervisor: ServerSupervisor | None,
    launch_claude: ClaudeLauncher,
) -> None:
    """Run the intentionally small line-oriented FCC terminal menu."""

    while True:
        _print_home(settings, supervisor=supervisor)
        try:
            choice = input("FCC> ").strip().casefold()
        except EOFError, KeyboardInterrupt:
            print()
            return

        if choice in {"", "c", "claude"}:
            launch_claude(False, ())
        elif choice in {"d", "danger"}:
            launch_claude(True, ())
        elif choice in {"x", "connect", "codex"}:
            _connect_codex()
        elif choice in {"p", "policy", "status"}:
            _print_policy_status(settings)
        elif choice in {"s", "settings"}:
            _run_settings_menu(settings)
        elif choice in {"l", "logs"}:
            _print_logs(server_log_path())
        elif choice in {"r", "restart"}:
            if supervisor is None:
                print(
                    "Server is owned by another process; restart is unavailable here."
                )
            elif supervisor.request_restart():
                print("FCC server restart requested.")
            else:
                print("FCC server is not in a restartable state.")
        elif choice in {"q", "quit", "exit"}:
            return
        else:
            print("Unknown command. Use Enter/C, D, X, P, S, L, R, or Q.")


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
    model = _current_admin_value(settings, "MODEL", fallback=settings.model)
    print()
    print("FCC Harness")
    print("-----------")
    print(f"Server    {status} ({owner})")
    print(f"Model     {model}")
    print(f"Profile   {configured_profile()}")
    print(f"Context   {context_cap_tokens(os.environ):,} tokens")
    print()
    print("[Enter/C] Claude   [D] Danger   [X] Connect Codex")
    print("[P] Policy status  [S] Settings  [L] Logs     [R] Restart   [Q] Quit")


def _print_policy_status(settings: Settings) -> None:
    """Print the live policy receipt only after an explicit terminal request."""

    try:
        status = get_admin_status(settings)
    except LocalAdminError as exc:
        print(f"Policy status unavailable: {exc}")
        return
    policy = status.get("session_policy")
    if not isinstance(policy, Mapping):
        print("Policy status unavailable: server did not publish a session policy.")
        return
    print()
    print("Session policy")
    print("--------------")
    print(
        "Controller    "
        f"{policy.get('controller_provider')}/{policy.get('controller_model')}"
    )
    print(f"Provider mode {policy.get('provider_policy_mode')}")
    print(f"Route mode    {policy.get('capability_routing_mode')}")
    print(
        "Helpers       "
        f"{', '.join(_string_values(policy.get('allowed_helpers'))) or 'none'}"
    )
    print(f"Paid fallback {policy.get('paid_fallback')}")
    egress = policy.get("egress")
    if isinstance(egress, Mapping):
        print(f"Egress        {json.dumps(egress, sort_keys=True)}")


def _string_values(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _run_settings_menu(settings: Settings) -> None:
    """Edit the small high-value settings surface through the Admin API."""

    while True:
        try:
            config = get_admin_config(settings)
        except LocalAdminError as exc:
            print(f"Settings unavailable: {exc}")
            return
        fields = _field_map(config)
        model = fields.get("MODEL", {})
        reasoning = fields.get("REASONING_POLICY", {})
        print()
        print("Settings")
        print("--------")
        print(f"Managed config  {managed_env_path()}")
        print(f"Model           {_field_value(model, settings.model)}")
        print(
            "Reasoning       "
            f"{_field_value(reasoning, settings.reasoning_policy.value)}"
        )
        print(f"Profile         {configured_profile()}")
        print(f"Context         {context_cap_tokens(os.environ):,} tokens")
        print()
        print("[M] Model   [R] Reasoning   [B] Back")
        try:
            choice = input("Settings> ").strip().casefold()
        except EOFError, KeyboardInterrupt:
            print()
            return

        if choice in {"b", "back", "q", "quit"}:
            return
        if choice in {"m", "model"}:
            _edit_setting(
                settings,
                model,
                key="MODEL",
                prompt="Model (provider/model)> ",
            )
            continue
        if choice in {"r", "reasoning"}:
            options = _field_options(reasoning)
            if options:
                print("Reasoning choices: " + ", ".join(options))
            _edit_setting(
                settings,
                reasoning,
                key="REASONING_POLICY",
                prompt="Reasoning> ",
            )
            continue
        print("Unknown setting. Use M, R, or B.")


def _edit_setting(
    settings: Settings,
    field: dict[str, Any],
    *,
    key: str,
    prompt: str,
) -> None:
    if not field:
        print(f"{key} is not exposed by the canonical Admin manifest.")
        return
    if field.get("locked") is True:
        source = str(field.get("source", "external source"))
        print(f"{key} is locked by {source}; change it at that source instead.")
        return
    try:
        value = input(prompt).strip()
    except EOFError, KeyboardInterrupt:
        print()
        return
    if not value:
        print("No change.")
        return
    try:
        result = apply_admin_values(settings, {key: value})
    except LocalAdminError as exc:
        print(f"Could not apply {key}: {exc}")
        return
    _print_apply_result(key, result)


def _print_apply_result(key: str, result: dict[str, Any]) -> None:
    if result.get("applied") is not True:
        errors = result.get("errors")
        if isinstance(errors, list) and errors:
            print(f"Rejected {key}: " + "; ".join(str(error) for error in errors))
        else:
            print(f"Rejected {key}.")
        return
    print(f"Applied {key}.")
    restart = result.get("restart")
    if isinstance(restart, dict) and restart.get("automatic") is True:
        print("FCC is applying the required server restart.")


def _field_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields = config.get("fields")
    if not isinstance(fields, list):
        return {}
    mapped: dict[str, dict[str, Any]] = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        key = field.get("key")
        if isinstance(key, str):
            mapped[key] = field
    return mapped


def _field_value(field: dict[str, Any], fallback: str) -> str:
    value = field.get("value")
    return str(value) if value is not None else fallback


def _field_options(field: dict[str, Any]) -> tuple[str, ...]:
    options = field.get("options")
    if not isinstance(options, list):
        return ()
    values: list[str] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        value = option.get("value")
        if isinstance(value, str) and value:
            values.append(value)
    return tuple(values)


def _current_admin_value(settings: Settings, key: str, *, fallback: str) -> str:
    try:
        field = _field_map(get_admin_config(settings)).get(key, {})
    except LocalAdminError:
        return fallback
    return _field_value(field, fallback)


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


def _codex_subscription_environment() -> dict[str, str]:
    """Build a Codex child env that cannot silently prefer API-key auth."""

    environment = dict(os.environ)
    for key in _CODEX_API_ENV_KEYS:
        environment.pop(key, None)
    return environment


def _codex_chatgpt_connected(executable: str) -> bool:
    """Return whether Codex reports an active ChatGPT sign-in."""

    try:
        result = subprocess.run(
            [executable, "login", "status"],
            env=_codex_subscription_environment(),
            capture_output=True,
            text=True,
            check=False,
            timeout=CODEX_STATUS_TIMEOUT_SECONDS,
        )
    except OSError, subprocess.TimeoutExpired:
        return False
    output = f"{result.stdout}\n{result.stderr}".casefold()
    return result.returncode == 0 and "logged in using chatgpt" in output


def _connect_codex() -> None:
    """Explicitly connect the installed Codex CLI with ChatGPT subscription auth."""

    executable = shutil.which("codex")
    if executable is None:
        print("Codex CLI was not found on PATH. Install/open Codex, then retry.")
        return
    if _codex_chatgpt_connected(executable):
        print("Codex is already connected using ChatGPT.")
        return

    print("Starting Codex ChatGPT sign-in; Harness will not use an API key.")
    try:
        result = subprocess.run(
            [executable, "login"],
            env=_codex_subscription_environment(),
            check=False,
        )
    except OSError as exc:
        print(f"Could not start Codex login: {type(exc).__name__}.")
        return
    if result.returncode != 0:
        print(f"Codex login exited with status {result.returncode}.")
        return
    if _codex_chatgpt_connected(executable):
        print("Codex connected using ChatGPT subscription auth.")
    else:
        print("Codex login finished, but ChatGPT connection was not confirmed.")


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
