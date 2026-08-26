"""Small terminal control surface over the canonical FCC server lifecycle."""

import getpass
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

from free_claude_code.application.connected_accounts import ConnectedAccountLoginMode
from free_claude_code.cli.claude_env import context_cap_tokens
from free_claude_code.cli.commands import ServerStatus, ServerSupervisor
from free_claude_code.cli.launchers.common import preflight_proxy
from free_claude_code.cli.local_admin import (
    LocalAdminError,
    apply_admin_values,
    cancel_connected_account_login,
    connected_account_status,
    disconnect_connected_account,
    get_admin_config,
    get_local_provider_status,
    get_models,
    get_usage,
    route_diagnostic,
    start_connected_account_login,
    test_provider,
    get_admin_status,
)
from free_claude_code.config.paths import managed_env_path, server_log_path
from free_claude_code.config.provider_catalog import (
    PROVIDER_CATALOG,
    ProviderAuthKind,
)
from free_claude_code.config.server_urls import local_proxy_root_url
from free_claude_code.config.settings import Settings, get_settings
from free_claude_code.learning.config import configured_profile, profile_home

CONTROL_STARTUP_TIMEOUT_SECONDS = 30.0
CODEX_STATUS_TIMEOUT_SECONDS = 5.0
LOG_PREVIEW_LINES = 30
_CODEX_API_ENV_KEYS = ("OPENAI_API_KEY", "CODEX_API_KEY")
ControlClientLauncher = Callable[[bool, Sequence[str]], None]


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
    launch_client: ControlClientLauncher,
    initial_argv: Sequence[str] | None = None,
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
            launch_client(False, initial_argv)
        run_control_menu(
            settings,
            supervisor=supervisor,
            launch_client=launch_client,
        )
    finally:
        supervisor.request_stop()
        server_thread.join()


def run_attached_control_center(
    settings: Settings,
    *,
    launch_client: ControlClientLauncher,
) -> None:
    """Use the terminal menu with an FCC server owned by another process."""

    run_control_menu(settings, supervisor=None, launch_client=launch_client)


def run_control_menu(
    settings: Settings,
    *,
    supervisor: ServerSupervisor | None,
    launch_client: ControlClientLauncher,
) -> None:
    """Run the intentionally small line-oriented FCC terminal menu."""

    displayed_model = settings.model
    while True:
        _print_home(settings, supervisor=supervisor, model=displayed_model)
        try:
            choice = input("FCC> ").strip().casefold()
        except EOFError, KeyboardInterrupt:
            print()
            return

        if choice in {"", "c", "claude"}:
            launch_client(False, ())
        elif choice in {"d", "danger"}:
            launch_client(True, ())
        elif choice in {"x", "connect", "codex"}:
            _connect_codex()
        elif choice in {"p", "providers", "accounts"}:
            _run_provider_menu(settings)
        elif choice in {"m", "models"}:
            _run_models_menu(settings)
        elif choice in {"u", "usage"}:
            _run_usage_menu(settings)
        elif choice in {"n", "diagnose", "diagnostics"}:
            _run_diagnostics_menu(settings)
        elif choice in {"y", "policy", "status"}:
            _print_policy_status(settings)
        elif choice in {"s", "settings"}:
            updated_model = _run_settings_menu(settings)
            if updated_model is not None:
                displayed_model = updated_model
        elif choice in {"l", "logs"}:
            _run_logs_menu()
        elif choice in {"f", "profile", "profiles"}:
            _print_profile()
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
            print("Unknown command. Use C, D, P, M, U, N, Y, X, S, L, F, R, or Q.")


def _print_home(
    settings: Settings,
    *,
    supervisor: ServerSupervisor | None,
    model: str | None = None,
) -> None:
    owner = "this terminal" if supervisor is not None else "another process"
    status = (
        supervisor.status.value
        if supervisor is not None
        else ServerStatus.RUNNING.value
    )
    displayed_model = settings.model if model is None else model
    print()
    print("FCC Harness")
    print("-----------")
    print(f"Server    {status} ({owner})")
    print(f"Model     {displayed_model}")
    print(f"Profile   {configured_profile()}")
    print(f"Context   {context_cap_tokens(os.environ):,} tokens")
    print()
    print("[Enter/C] Claude   [D] Danger   [P] Providers  [M] Models")
    print("[U] Usage          [N] Diagnose [Y] Policy   [X] Connect")
    print("[S] Settings       [L] Logs     [F] Profile [R] Restart  [Q] Quit")


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


def _run_settings_menu(settings: Settings) -> str | None:
    """Edit the small high-value settings surface through the Admin API."""

    displayed_model: str | None = None
    while True:
        try:
            config = get_admin_config(settings)
        except LocalAdminError as exc:
            print(f"Settings unavailable: {exc}")
            return displayed_model
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
            return displayed_model

        if choice in {"b", "back", "q", "quit"}:
            return displayed_model
        if choice in {"m", "model"}:
            changed_model = _edit_setting(
                settings,
                model,
                key="MODEL",
                prompt="Model (provider/model)> ",
            )
            if changed_model is not None:
                displayed_model = changed_model
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
) -> str | None:
    if not field:
        print(f"{key} is not exposed by the canonical Admin manifest.")
        return None
    if field.get("locked") is True:
        source = str(field.get("source", "external source"))
        print(f"{key} is locked by {source}; change it at that source instead.")
        return None
    try:
        value = input(prompt).strip()
    except EOFError, KeyboardInterrupt:
        print()
        return None
    if not value:
        print("No change.")
        return None
    try:
        result = apply_admin_values(settings, {key: value})
    except LocalAdminError as exc:
        print(f"Could not apply {key}: {exc}")
        return None
    if result.get("applied") is True:
        get_settings.cache_clear()
        if key == "MODEL":
            settings.model = value
    _print_apply_result(key, result)
    return value if result.get("applied") is True and key == "MODEL" else None


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


def _run_provider_menu(settings: Settings) -> None:
    """Navigate provider status and actions through the canonical Admin API."""

    try:
        config = get_admin_config(settings)
    except LocalAdminError as exc:
        print(f"Providers unavailable: {exc}")
        return
    statuses = _provider_statuses(config)
    if not statuses:
        print("No providers are present in the canonical provider catalog.")
        return

    while True:
        print()
        print("Providers & Accounts")
        print("--------------------")
        for index, provider in enumerate(statuses, start=1):
            print(
                f"{index:>2}. {provider.get('display_name', provider.get('provider_id', '?'))}"
                f" [{provider.get('label', provider.get('status', 'unknown'))}]"
            )
        print("Enter a number or provider id. [B] Back")
        try:
            selection = input("Provider> ").strip()
        except EOFError, KeyboardInterrupt:
            print()
            return
        if selection.casefold() in {"b", "back", "q", "quit"}:
            return
        provider = _select_provider(statuses, selection)
        if provider is None:
            print("Unknown provider selection.")
            continue
        _run_provider_detail(settings, provider, config)
        try:
            config = get_admin_config(settings)
            statuses = _provider_statuses(config)
        except LocalAdminError as exc:
            print(f"Provider refresh unavailable: {exc}")
            return


def _provider_statuses(config: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    statuses = config.get("provider_status")
    if not isinstance(statuses, list):
        return ()
    return tuple(status for status in statuses if isinstance(status, dict))


def _select_provider(
    statuses: Sequence[dict[str, Any]], selection: str
) -> dict[str, Any] | None:
    if selection.isdigit():
        index = int(selection) - 1
        return statuses[index] if 0 <= index < len(statuses) else None
    normalized = selection.casefold()
    for provider in statuses:
        if normalized in {
            str(provider.get("provider_id", "")).casefold(),
            str(provider.get("display_name", "")).casefold(),
        }:
            return provider
    return None


def _run_provider_detail(
    settings: Settings,
    provider: dict[str, Any],
    config: dict[str, Any],
) -> None:
    provider_id = str(provider.get("provider_id", ""))
    if not provider_id:
        return
    descriptor = PROVIDER_CATALOG.get(provider_id)
    fields = _provider_fields(config, provider_id)
    while True:
        account_status: dict[str, Any] | None = None
        if (
            descriptor is not None
            and descriptor.auth_kind is ProviderAuthKind.CONNECTED_ACCOUNT
        ):
            try:
                account_status = connected_account_status(settings, provider_id)
            except LocalAdminError as exc:
                print(f"Connected-account status unavailable: {exc}")
        print()
        print(f"{provider.get('display_name', provider_id)} ({provider_id})")
        print(f"Status: {provider.get('label', provider.get('status', 'unknown'))}")
        if account_status is not None:
            print(f"Account: {account_status.get('state', 'unknown')}")
            if account_status.get("email"):
                print(f"Email: {account_status['email']}")
            if account_status.get("model_count") is not None:
                print(f"Cached models: {account_status['model_count']}")
        if fields:
            for key, field in fields:
                value = (
                    "configured"
                    if field.get("configured")
                    else "missing"
                    if field.get("secret")
                    else _field_value(field, "")
                )
                print(f"  {key}: {value}")
        if (
            descriptor is not None
            and descriptor.auth_kind is ProviderAuthKind.CONNECTED_ACCOUNT
        ):
            print("[L] Browser login  [D] Device login  [C] Cancel  [X] Disconnect")
        else:
            print("[E] Edit field     [T] Test provider")
            if descriptor is not None and descriptor.local:
                print("[R] Check local reachability")
        print("[B] Back")
        try:
            choice = input("Provider action> ").strip().casefold()
        except EOFError, KeyboardInterrupt:
            print()
            return
        if choice in {"b", "back", "q", "quit"}:
            return
        if (
            descriptor is not None
            and descriptor.auth_kind is ProviderAuthKind.CONNECTED_ACCOUNT
        ):
            if choice in {"l", "browser"}:
                _start_account_login(
                    settings, provider_id, ConnectedAccountLoginMode.BROWSER
                )
            elif choice in {"d", "device"}:
                _start_account_login(
                    settings, provider_id, ConnectedAccountLoginMode.DEVICE
                )
            elif choice in {"c", "cancel"}:
                _account_action(
                    settings,
                    provider_id,
                    cancel_connected_account_login,
                    "Login cancelled",
                )
            elif choice in {"x", "disconnect"}:
                _account_action(
                    settings,
                    provider_id,
                    disconnect_connected_account,
                    "Account disconnected",
                )
            else:
                print("Unknown account action.")
            continue
        if choice in {"e", "edit", "key"}:
            _edit_provider_fields(settings, fields)
        elif choice in {"t", "test"}:
            _test_provider(settings, provider_id)
        elif choice in {"r", "reachability", "local"}:
            _show_local_provider(settings, provider_id)
        else:
            print("Unknown provider action.")


def _provider_fields(
    config: dict[str, Any], provider_id: str
) -> tuple[tuple[str, dict[str, Any]], ...]:
    field_map = _field_map(config)
    descriptor = PROVIDER_CATALOG.get(provider_id)
    if descriptor is None:
        return ()
    settings_attrs = list(descriptor.configuration_attrs())
    for settings_attr in (descriptor.base_url_attr, descriptor.proxy_attr):
        if settings_attr is not None and settings_attr not in settings_attrs:
            settings_attrs.append(settings_attr)
    keys: list[str] = []
    for settings_attr in settings_attrs:
        if settings_attr == descriptor.credential_attr and descriptor.credential_env:
            keys.append(descriptor.credential_env)
            continue
        field = Settings.model_fields.get(settings_attr)
        if field is None:
            continue
        alias = field.validation_alias
        if alias is not None:
            keys.append(str(alias))
        elif field.alias is not None:
            keys.append(str(field.alias))
        else:
            keys.append(settings_attr.upper())
    return tuple((key, field_map[key]) for key in keys if key in field_map)


def _edit_provider_fields(
    settings: Settings, fields: tuple[tuple[str, dict[str, Any]], ...]
) -> None:
    if not fields:
        print("No editable fields are exposed for this provider.")
        return
    for index, (key, field) in enumerate(fields, start=1):
        marker = "secret" if field.get("secret") else "text"
        print(f"{index}. {field.get('label', key)} ({marker})")
    try:
        selection = input("Field (or B)> ").strip()
    except EOFError, KeyboardInterrupt:
        print()
        return
    if selection.casefold() in {"b", "back"} or not selection.isdigit():
        return
    index = int(selection) - 1
    if not 0 <= index < len(fields):
        print("Unknown field.")
        return
    key, field = fields[index]
    if field.get("locked") is True:
        print(f"{key} is locked by {field.get('source', 'an external source')}.")
        return
    try:
        value = (
            getpass.getpass(f"{field.get('label', key)} (hidden)> ")
            if field.get("secret")
            else input(f"{field.get('label', key)}> ")
        ).strip()
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


def _test_provider(settings: Settings, provider_id: str) -> None:
    try:
        result = test_provider(settings, provider_id)
    except LocalAdminError as exc:
        print(f"Provider test failed: {exc}")
        return
    if result.get("ok") is not True:
        print(f"Provider test failed ({result.get('error_type', 'unknown error')}).")
        return
    models = result.get("models")
    count = len(models) if isinstance(models, list) else 0
    print(f"Provider test passed; {count} model(s) discovered.")


def _show_local_provider(settings: Settings, provider_id: str) -> None:
    try:
        result = get_local_provider_status(settings)
    except LocalAdminError as exc:
        print(f"Local provider check failed: {exc}")
        return
    providers = result.get("providers")
    if not isinstance(providers, list):
        print("No local-provider status was returned.")
        return
    match = next(
        (
            entry
            for entry in providers
            if isinstance(entry, dict) and entry.get("provider_id") == provider_id
        ),
        None,
    )
    if match is None:
        print("No status was returned for that local provider.")
    else:
        print(f"{provider_id}: {match.get('label', match.get('status', 'unknown'))}")


def _start_account_login(
    settings: Settings, provider_id: str, mode: ConnectedAccountLoginMode
) -> None:
    try:
        status = start_connected_account_login(settings, provider_id, mode)
    except LocalAdminError as exc:
        print(f"Could not start {mode.value} login: {exc}")
        return
    print(f"Login state: {status.get('state', 'unknown')}")
    url = status.get("authorization_url") or status.get("verification_url")
    if isinstance(url, str) and url:
        print(f"Open this URL in a browser: {url}")
    code = status.get("user_code")
    if isinstance(code, str) and code:
        print(f"Device code: {code}")


def _account_action(
    settings: Settings,
    provider_id: str,
    action: Callable[[Settings, str], dict[str, Any]],
    success_message: str,
) -> None:
    try:
        status = action(settings, provider_id)
    except LocalAdminError as exc:
        print(f"Account action failed: {exc}")
        return
    print(f"{success_message}: {status.get('state', 'unknown')}")


def _run_models_menu(settings: Settings) -> None:
    while True:
        try:
            result = get_models(settings)
        except LocalAdminError as exc:
            print(f"Models unavailable: {exc}")
            return
        models = result.get("models")
        model_list = (
            [str(model) for model in models] if isinstance(models, list) else []
        )
        print()
        print(f"Models ({len(model_list)})")
        print("--------")
        for model in model_list[:60]:
            print(f"  {model}")
        if len(model_list) > 60:
            print(f"  ... {len(model_list) - 60} more")
        failed = result.get("failed_providers")
        if isinstance(failed, list) and failed:
            print("Refresh failures: " + ", ".join(str(item) for item in failed))
        try:
            choice = input("Models> [R]efresh [B]ack: ").strip().casefold()
        except EOFError, KeyboardInterrupt:
            print()
            return
        if choice in {"b", "back", "q", "quit", ""}:
            return
        if choice in {"r", "refresh"}:
            try:
                result = get_models(settings, refresh=True)
            except LocalAdminError as exc:
                print(f"Model refresh failed: {exc}")
                continue
            print(f"Model refresh completed ({len(result.get('models', []))} visible).")
        else:
            print("Unknown models action.")


def _run_usage_menu(settings: Settings) -> None:
    try:
        raw_days = input("Usage range in days [30]: ").strip()
    except EOFError, KeyboardInterrupt:
        print()
        return
    days = 30 if not raw_days else int(raw_days) if raw_days.isdigit() else 0
    if days < 1 or days > 366:
        print("Usage range must be between 1 and 366 days.")
        return
    try:
        result = get_usage(settings, days=days)
    except (LocalAdminError, ValueError) as exc:
        print(f"Usage unavailable: {exc}")
        return
    totals = result.get("totals")
    print()
    print(f"Usage ({days} days)")
    print("--------------")
    if isinstance(totals, dict) and totals:
        for key, value in totals.items():
            print(f"{key}: {value}")
    else:
        print("No recorded usage.")
    models = result.get("models")
    if isinstance(models, list) and models:
        print("By model:")
        for row in models[:20]:
            if isinstance(row, dict):
                print("  " + ", ".join(f"{key}={value}" for key, value in row.items()))


def _run_diagnostics_menu(settings: Settings) -> None:
    try:
        model = input(f"Model [{settings.model}]: ").strip() or settings.model
        shapes_text = input("Capability shapes [text]: ").strip() or "text"
        mode = input("Routing mode [strict]: ").strip() or "strict"
    except EOFError, KeyboardInterrupt:
        print()
        return
    shapes = tuple(shape.strip() for shape in shapes_text.split(",") if shape.strip())
    try:
        result = route_diagnostic(settings, model=model, shapes=shapes, mode=mode)
    except LocalAdminError as exc:
        print(f"Diagnostics unavailable: {exc}")
        return
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))


def _run_logs_menu() -> None:
    try:
        query = input("Log filter (blank for all): ").strip().casefold()
    except EOFError, KeyboardInterrupt:
        print()
        return
    lines = _tail_lines(server_log_path(), limit=LOG_PREVIEW_LINES)
    if query:
        lines = tuple(line for line in lines if query in line.casefold())
    print()
    print(f"Server logs — {server_log_path()}")
    print("-----------")
    if not lines:
        print("No matching log lines.")
    else:
        for line in lines:
            print(_render_log_line(line))


def _print_profile() -> None:
    print()
    print("Profile")
    print("-------")
    print(f"Name  {configured_profile()}")
    print(f"State {profile_home()}")
    print("Use fcc-learning or the canonical Admin/profile surface to change it.")


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
