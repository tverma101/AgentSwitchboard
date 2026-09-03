"""Shared process helpers for installed client CLI launchers."""

import json
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

from free_claude_code.cli.local_http import open_local_request
from free_claude_code.cli.process_registry import (
    kill_pid_tree_best_effort,
    register_pid,
    unregister_pid,
)
from free_claude_code.core.process_identity import set_process_identity
from free_claude_code.core.server_identity import (
    SERVER_HEALTH_PROTOCOL,
    SERVER_SERVICE_NAME,
)

PROXY_PREFLIGHT_PATH = "/health"
PROXY_PREFLIGHT_TIMEOUT_SECONDS = 1.5


class ServerProbeResult:
    """Credential-free result of probing one local FCC health endpoint."""

    def __init__(
        self,
        *,
        healthy: bool,
        error: str | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> None:
        self.healthy = healthy
        self.error = error
        self.payload = payload or {}

    @property
    def foreign(self) -> bool:
        """Whether a responsive endpoint failed FCC identity validation."""

        return (
            not self.healthy
            and self.error is not None
            and self.error.startswith("foreign service")
        )


def probe_server(
    proxy_root_url: str,
    *,
    expected_mode: str | None = None,
) -> ServerProbeResult:
    """Probe and validate the FCC health identity at a local URL."""

    url = f"{proxy_root_url.rstrip('/')}{PROXY_PREFLIGHT_PATH}"
    request = Request(url, method="GET")
    try:
        with open_local_request(
            request, timeout=PROXY_PREFLIGHT_TIMEOUT_SECONDS
        ) as response:
            status_code = response.getcode()
            raw_body = response.read()
    except HTTPError as exc:
        return ServerProbeResult(healthy=False, error=f"returned HTTP {exc.code}")
    except URLError as exc:
        return ServerProbeResult(healthy=False, error=str(exc.reason))
    except OSError as exc:
        return ServerProbeResult(healthy=False, error=str(exc))

    if not 200 <= status_code < 300:
        return ServerProbeResult(healthy=False, error=f"returned HTTP {status_code}")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except UnicodeDecodeError, json.JSONDecodeError:
        return ServerProbeResult(
            healthy=False,
            error="foreign service: health response was not FCC JSON",
        )
    if not isinstance(payload, dict):
        return ServerProbeResult(
            healthy=False, error="foreign service: health response was not an object"
        )
    if (
        payload.get("service") != SERVER_SERVICE_NAME
        or payload.get("protocol") != SERVER_HEALTH_PROTOCOL
    ):
        return ServerProbeResult(
            healthy=False,
            error="foreign service: FCC identity is missing or unsupported",
            payload=payload,
        )
    if expected_mode is not None and payload.get("mode") != expected_mode:
        return ServerProbeResult(
            healthy=False,
            error=(
                f"foreign service: expected FCC mode {expected_mode!r}, "
                f"found {payload.get('mode', 'unknown')!r}"
            ),
            payload=payload,
        )
    return ServerProbeResult(healthy=True, payload=payload)


def preflight_proxy(
    proxy_root_url: str,
    *,
    expected_mode: str | None = None,
) -> str | None:
    """Return an error message when the local proxy health check is unreachable."""

    if expected_mode is None:
        # Preserve the lightweight compatibility probe for client launchers that
        # only need to know whether an HTTP listener is accepting requests.
        url = f"{proxy_root_url.rstrip('/')}{PROXY_PREFLIGHT_PATH}"
        request = Request(url, method="GET")
        try:
            with open_local_request(
                request, timeout=PROXY_PREFLIGHT_TIMEOUT_SECONDS
            ) as response:
                status_code = response.getcode()
        except HTTPError as exc:
            return f"returned HTTP {exc.code}"
        except URLError as exc:
            return str(exc.reason)
        except OSError as exc:
            return str(exc)
        return None if 200 <= status_code < 300 else f"returned HTTP {status_code}"
    result = probe_server(proxy_root_url, expected_mode=expected_mode)
    return None if result.healthy else result.error


class ClientLaunchError(RuntimeError):
    """A client launch failed while called from an interactive control surface."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def resolve_client_binary(
    *,
    binary_name: str,
    display_name: str,
    install_hint: str,
    raise_for_control: bool = False,
) -> str:
    """Resolve an installed client binary or exit with a user-facing hint."""

    client_command = shutil.which(binary_name)
    if client_command is None:
        message = (
            f"Could not find {display_name} command: {binary_name}\n{install_hint}"
        )
        if raise_for_control:
            raise ClientLaunchError(message, 127)
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
    cwd: Path | None = None,
    raise_for_control: bool = False,
) -> None:
    """Run a client CLI command and mirror its exit code."""

    set_process_identity(f"{display_name} launcher")
    process: subprocess.Popen[bytes] | None = None
    try:
        if cwd is None:
            process = subprocess.Popen(command, env=dict(env))
        else:
            process = subprocess.Popen(command, env=dict(env), cwd=str(cwd))
        if process.pid:
            register_pid(process.pid)
        return_code = process.wait()
    except FileNotFoundError:
        message = (
            f"Could not find {display_name} command: {binary_name}\n{install_hint}"
        )
        if raise_for_control:
            raise ClientLaunchError(message, 127) from None
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

    if raise_for_control:
        if return_code == 0:
            return
        raise ClientLaunchError(
            f"{display_name} exited with status {return_code}.",
            return_code,
        )
    raise SystemExit(return_code)
