"""Shared process helpers for installed client CLI launchers."""

import json
import shutil
import subprocess
import sys
from collections.abc import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request

from free_claude_code.cli.local_http import open_local_request
from free_claude_code.cli.process_registry import (
    kill_pid_tree_best_effort,
    register_pid,
    unregister_pid,
)
from free_claude_code.core.version import package_version

PROXY_PREFLIGHT_PATH = "/health"
PROXY_PREFLIGHT_TIMEOUT_SECONDS = 1.5
_PROXY_VERSION_MISMATCH_PREFIX = "FCC version mismatch:"


def preflight_proxy(proxy_root_url: str) -> str | None:
    """Return an error when the local proxy is unreachable or incompatible."""

    url = f"{proxy_root_url.rstrip('/')}{PROXY_PREFLIGHT_PATH}"
    request = Request(url, method="GET")
    body: bytes | None = None
    try:
        with open_local_request(request, timeout=PROXY_PREFLIGHT_TIMEOUT_SECONDS) as response:
            status_code = response.getcode()
            if 200 <= status_code < 300:
                body = response.read()
    except HTTPError as exc:
        return f"returned HTTP {exc.code}"
    except URLError as exc:
        return str(exc.reason)
    except OSError as exc:
        return str(exc)

    if not 200 <= status_code < 300:
        return f"returned HTTP {status_code}"
    if body is None:
        return "FCC health endpoint returned no body"
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "FCC health endpoint returned invalid JSON"
    if not isinstance(payload, dict) or payload.get("status") != "healthy":
        return "FCC health endpoint returned an invalid payload"

    running_version = payload.get("version")
    expected_version = package_version()
    if running_version != expected_version:
        display_version = (
            running_version
            if isinstance(running_version, str) and running_version
            else "unknown"
        )
        return (
            f"{_PROXY_VERSION_MISMATCH_PREFIX} running {display_version}, "
            f"installed {expected_version}"
        )
    return None


def is_proxy_version_mismatch(error: str | None) -> bool:
    """Return whether a preflight error identifies an older/newer FCC daemon."""

    return isinstance(error, str) and error.startswith(_PROXY_VERSION_MISMATCH_PREFIX)


def resolve_client_binary(
    *,
    binary_name: str,
    display_name: str,
    install_hint: str,
) -> str:
    """Resolve an installed client binary or exit with a user-facing hint."""

    client_command = shutil.which(binary_name)
    if client_command is None:
        print(
            f"Could not find {display_name} command: {binary_name}",
            file=sys.stderr,
        )
        print(install_hint, file=sys.stderr)
        raise SystemExit(127)
    return client_command


def run_client_process(
    *,
    command: list[str],
    env: Mapping[str, str],
    binary_name: str,
    display_name: str,
    install_hint: str,
) -> None:
    """Run a client CLI command and mirror its exit code."""

    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(command, env=dict(env))
        if process.pid:
            register_pid(process.pid)
        return_code = process.wait()
    except FileNotFoundError:
        print(
            f"Could not find {display_name} command: {binary_name}",
            file=sys.stderr,
        )
        print(install_hint, file=sys.stderr)
        raise SystemExit(127) from None
    except KeyboardInterrupt:
        if process is not None and process.pid:
            kill_pid_tree_best_effort(process.pid)
            process.wait()
        raise
    finally:
        if process is not None and process.pid:
            unregister_pid(process.pid)

    raise SystemExit(return_code)
