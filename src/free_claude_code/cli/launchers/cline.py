"""Installed ``fcc-cline`` launcher for the local FCC Anthropic bridge."""

import argparse
import json
import os
import stat
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from free_claude_code.cli.launchers.common import (
    preflight_proxy,
    resolve_client_binary,
    run_client_process,
)
from free_claude_code.config.server_urls import local_proxy_root_url
from free_claude_code.config.settings import get_settings

_DISPLAY_NAME = "Cline"
_INSTALL_HINT = "Install Cline from https://cline.bot/"
_DEFAULT_DATA_DIR = Path.home() / ".cline" / "data"
_PROVIDER_SETTINGS_FILENAME = "providers.json"
_LOCAL_PROVIDER_ID = "anthropic"


class ClineBridgeError(ValueError):
    """A local Cline bridge configuration could not be prepared."""


def launch(argv: Sequence[str] | None = None) -> None:
    """Configure Cline's local Anthropic provider and launch Cline."""

    args = list(sys.argv[1:] if argv is None else argv)
    bridge_args, cline_args = _parse_bridge_args(args)
    settings = get_settings()
    proxy_root_url = local_proxy_root_url(settings)
    if error := preflight_proxy(proxy_root_url):
        _fail(
            f"Free Claude Code proxy is not reachable at {proxy_root_url}: {error}\n"
            "Start it in another terminal with: fcc-server"
        )

    model = bridge_args.model or settings.model
    _validate_model_ref(model)
    data_dir = bridge_args.data_dir or _cline_data_dir(cline_args)
    settings_path = data_dir / "settings" / _PROVIDER_SETTINGS_FILENAME
    binary_path: str | None = None
    if not bridge_args.dry_run:
        binary_path = resolve_client_binary(
            binary_name="cline",
            display_name=_DISPLAY_NAME,
            install_hint=_INSTALL_HINT,
        )
    try:
        changed = _ensure_local_provider(
            settings_path,
            base_url=f"{proxy_root_url}/v1",
            auth_token=settings.anthropic_auth_token,
            model=model,
            dry_run=bridge_args.dry_run,
        )
    except (ClineBridgeError, OSError, json.JSONDecodeError) as exc:
        _fail(f"Could not configure the Cline FCC bridge: {exc}")

    if bridge_args.dry_run:
        status = "would update" if changed else "already configured"
        print(f"FCC Cline bridge: {status} {settings_path}")
        return

    if not _has_option(cline_args, "--provider", "-P"):
        cline_args[0:0] = ["--provider", _LOCAL_PROVIDER_ID]
    if not _has_option(cline_args, "--model", "-m"):
        cline_args[0:0] = ["--model", model]

    assert binary_path is not None
    run_client_process(
        command=[binary_path, *cline_args],
        env=os.environ,
        binary_name="cline",
        display_name=_DISPLAY_NAME,
        install_hint=_INSTALL_HINT,
    )


def _parse_bridge_args(args: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog="fcc-cline",
        description="Route Cline through the local AgentSwitchboard proxy.",
    )
    parser.add_argument(
        "--fcc-model",
        dest="model",
        help="FCC provider/model route (default: the configured MODEL route)",
    )
    parser.add_argument(
        "--fcc-data-dir",
        dest="data_dir",
        type=Path,
        help="Cline data directory (default: ~/.cline/data)",
    )
    parser.add_argument(
        "--fcc-dry-run",
        dest="dry_run",
        action="store_true",
        help="show the provider settings path without writing or launching",
    )
    namespace, remaining = parser.parse_known_args(args)
    return namespace, remaining


def _cline_data_dir(cline_args: Sequence[str]) -> Path:
    """Resolve Cline's data directory from its pass-through options."""

    for index, argument in enumerate(cline_args):
        if argument == "--data-dir" and index + 1 < len(cline_args):
            return Path(cline_args[index + 1]).expanduser()
        if argument.startswith("--data-dir="):
            return Path(argument.partition("=")[2]).expanduser()
    return _DEFAULT_DATA_DIR


def _ensure_local_provider(
    settings_path: Path,
    *,
    base_url: str,
    auth_token: str,
    model: str,
    dry_run: bool,
) -> bool:
    """Merge the local provider entry and report whether its content changed."""

    if not auth_token.strip():
        raise ClineBridgeError("FCC ANTHROPIC_AUTH_TOKEN is empty")
    if settings_path.exists():
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ClineBridgeError("providers.json must contain a JSON object")
    else:
        payload = {"version": 1, "providers": {}}

    providers = payload.get("providers")
    if providers is None:
        providers = {}
        payload["providers"] = providers
    if not isinstance(providers, dict):
        raise ClineBridgeError("providers must be a JSON object")

    current = providers.get(_LOCAL_PROVIDER_ID)
    if current is not None and not isinstance(current, dict):
        raise ClineBridgeError("the anthropic provider entry must be a JSON object")
    entry = dict(current) if isinstance(current, dict) else {}
    provider_settings = entry.get("settings")
    if provider_settings is not None and not isinstance(provider_settings, dict):
        raise ClineBridgeError("the anthropic settings entry must be a JSON object")
    entry["settings"] = {
        **(provider_settings if isinstance(provider_settings, dict) else {}),
        "provider": _LOCAL_PROVIDER_ID,
        "apiKey": auth_token,
        "model": model,
        "baseUrl": base_url,
    }
    entry.setdefault("tokenSource", "manual")
    providers[_LOCAL_PROVIDER_ID] = entry

    changed_payload = payload != _read_json_if_present(settings_path)
    if changed_payload and not dry_run:
        _atomic_write_json(settings_path, payload)
    return changed_payload


def _read_json_if_present(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        os.replace(temporary_path, path)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _validate_model_ref(model: str) -> None:
    if not model.strip() or "/" not in model:
        raise ClineBridgeError(
            "FCC model must be an exact provider/model route, for example "
            "bai/deepseek-v4-flash"
        )


def _has_option(args: Sequence[str], *options: str) -> bool:
    return any(
        argument in options
        or any(argument.startswith(f"{option}=") for option in options)
        for argument in args
    )


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


__all__ = [
    "ClineBridgeError",
    "launch",
]
