"""Current Codex-managed Computer Use host contract.

This is the native-parity path for #102. It mirrors the Computer Use launcher
shipped by the installed ChatGPT/Codex app and keeps Luna as the controller.
The older isolated direct-client broker remains available only as a diagnostic
fallback for installations where the managed launcher is absent.

Current host behavior was cross-checked against:
- fitchmultz/macuse @ 447df521 (MIT), Aug 2026 external-harness validation;
- openclaw/openclaw @ c2602193, current Computer Use readiness/lifecycle logic;
- iFurySt/open-codex-computer-use @ ead48da2, app-server status/tool transport.
"""

import os
import queue
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from free_claude_code.runtime.codex_computer_use import (
    COMPUTER_USE_METHODS,
    CodexComputerUseBroker,
    CodexComputerUseError,
    CodexComputerUsePaths,
    interaction_requires_fresh_state,
)

FEATURE_FLAGS = ("computer_use", "plugins", "tool_call_mcp_elicitation")
SERVER_NAME = "computer-use"
PLUGIN_RELATIVE_PATH = Path("plugins/openai-bundled/plugins/computer-use")
LAUNCHER_RELATIVE_PATH = Path("bin/computer-use-client-launcher")
READY_POLL_SECONDS = 0.1
MAX_STATUS_PAGES = 10

ElicitationHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class CodexComputerUseIndeterminateError(CodexComputerUseError):
    """A mutating native call lost transport certainty after dispatch."""


class CodexComputerUseReadinessError(CodexComputerUseError):
    """The managed Computer Use MCP server never exposed its expected tools."""


class CodexComputerUseElicitationError(CodexComputerUseError):
    """A caller-provided app-approval decision was malformed."""


def managed_plugin_root(paths: CodexComputerUsePaths) -> Path | None:
    """Return the canonical bundled Computer Use plugin root when installed."""

    candidate = paths.codex.parent / PLUGIN_RELATIVE_PATH
    if not candidate.is_dir():
        return None
    canonical = candidate.resolve()
    resources = paths.codex.parent.resolve()
    try:
        canonical.relative_to(resources)
    except ValueError as error:
        raise CodexComputerUseError(
            "Codex Computer Use plugin escaped the signed app resources root"
        ) from error
    return canonical


def managed_launcher(paths: CodexComputerUsePaths) -> tuple[Path, Path] | None:
    """Resolve the bundled launcher without following an arbitrary external path."""

    plugin_root = managed_plugin_root(paths)
    if plugin_root is None:
        return None
    launcher = plugin_root / LAUNCHER_RELATIVE_PATH
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        return None
    canonical = launcher.resolve()
    try:
        canonical.relative_to(plugin_root)
    except ValueError as error:
        raise CodexComputerUseError(
            "Codex Computer Use launcher escaped the bundled plugin root"
        ) from error
    return plugin_root, canonical


def managed_broker_environment(
    *,
    temp_root: Path,
    user_home: Path | None = None,
    codex_home: Path | None = None,
) -> dict[str, str]:
    """Build a minimal native-like environment without API credential leakage."""

    home = (user_home or Path.home()).expanduser().resolve()
    resolved_codex_home = (
        codex_home
        or Path(os.environ.get("CODEX_HOME", str(home / ".codex"))).expanduser()
    ).resolve()
    env = {
        "HOME": str(home),
        "CODEX_HOME": str(resolved_codex_home),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "TMPDIR": str(temp_root),
        "NO_COLOR": "1",
        "CLICOLOR": "0",
    }
    for key in ("USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "SHELL", "TERM"):
        if value := os.environ.get(key):
            env[key] = value
    return env


def managed_app_server_args() -> list[str]:
    """Start current app-server features while making model execution unusable."""

    disabled_provider = (
        '{ name = "Computer Use only", base_url = "http://127.0.0.1:9/v1", '
        'wire_api = "responses", request_max_retries = 0, stream_max_retries = 0, '
        "supports_websockets = false, requires_openai_auth = false }"
    )
    args = [
        "-c",
        'model_provider="computer_use_disabled"',
        "-c",
        'model="computer-use-disabled"',
        "-c",
        f"model_providers.computer_use_disabled={disabled_provider}",
        "-c",
        "features.shell_tool=false",
        "-c",
        "features.unified_exec=false",
        "-c",
        "features.multi_agent=false",
        "-c",
        "features.memories=false",
        "-c",
        "memories.use_memories=false",
        "-c",
        "memories.generate_memories=false",
        "-c",
        "features.remote_control=false",
        "-c",
        "features.hooks=false",
        "-c",
        "analytics.enabled=false",
        "-c",
        'otel.exporter="none"',
        "-c",
        'web_search="disabled"',
        "-c",
        'history.persistence="none"',
        "app-server",
    ]
    for feature in FEATURE_FLAGS:
        args.extend(("--enable", feature))
    return args


def managed_mcp_config(paths: CodexComputerUsePaths) -> dict[str, Any]:
    """Mirror the installed launcher manifest, with direct client as fallback."""

    resolved = managed_launcher(paths)
    if resolved is not None:
        plugin_root, launcher = resolved
        return {
            "command": str(launcher),
            "args": ["mcp"],
            "cwd": str(plugin_root),
            "env_vars": ["CODEX_HOME"],
            "enabled": True,
        }
    return {
        "command": str(paths.client),
        "args": ["mcp"],
        "cwd": str(paths.app.parent),
        "enabled": True,
    }


def managed_thread_start_params(
    paths: CodexComputerUsePaths,
    work_dir: Path,
) -> dict[str, Any]:
    """Create one ephemeral native host thread with only Computer Use configured."""

    return {
        "cwd": str(work_dir),
        "ephemeral": True,
        "approvalPolicy": "on-request",
        "sandbox": "workspace-write",
        "serviceName": "fcc_codex_computer_use",
        "config": {
            "features": {
                "computer_use": True,
                "plugins": True,
                "tool_call_mcp_elicitation": True,
            },
            "mcp_servers": {SERVER_NAME: managed_mcp_config(paths)},
        },
    }


def _cancel_elicitation(_params: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"action": "cancel", "content": None, "_meta": None}


def _validate_elicitation_response(value: Mapping[str, Any]) -> dict[str, Any]:
    action = value.get("action")
    if action not in {"accept", "decline", "cancel"}:
        raise CodexComputerUseElicitationError(
            "Computer Use elicitation action must be accept, decline, or cancel"
        )
    response: dict[str, Any] = {"action": action}
    response["content"] = value.get("content")
    response["_meta"] = value.get("_meta")
    return response


def _tool_names(server: Mapping[str, Any]) -> frozenset[str]:
    tools = server.get("tools")
    if isinstance(tools, Mapping):
        return frozenset(str(name) for name in tools)
    if isinstance(tools, list):
        names: set[str] = set()
        for item in tools:
            if isinstance(item, Mapping) and isinstance(item.get("name"), str):
                names.add(item["name"])
        return frozenset(names)
    return frozenset()


class ManagedCodexComputerUseBroker(CodexComputerUseBroker):
    """Current managed plugin-launcher path with readiness and elicitation support."""

    def __init__(
        self,
        paths: CodexComputerUsePaths,
        *,
        timeout_seconds: float = 120.0,
        readiness_timeout_seconds: float = 45.0,
        elicitation_handler: ElicitationHandler | None = None,
        user_home: Path | None = None,
        codex_home: Path | None = None,
    ) -> None:
        super().__init__(paths, timeout_seconds=timeout_seconds)
        if readiness_timeout_seconds <= 0:
            raise ValueError("readiness_timeout_seconds must be positive")
        self.readiness_timeout_seconds = readiness_timeout_seconds
        self.elicitation_handler = elicitation_handler or _cancel_elicitation
        self.user_home = user_home
        self.codex_home = codex_home
        self._native_tool_names: frozenset[str] = frozenset()
        self._native_auth_status: str | None = None
        self._elicitation_count = 0

    @property
    def native_tool_names(self) -> frozenset[str]:
        return self._native_tool_names

    @property
    def native_auth_status(self) -> str | None:
        return self._native_auth_status

    @property
    def elicitation_count(self) -> int:
        return self._elicitation_count

    def start(self) -> None:
        if self.started:
            return
        self._fatal_error = None
        self._messages = queue.Queue()
        self._stderr = []
        self._native_tool_names = frozenset()
        self._native_auth_status = None
        self._elicitation_count = 0
        self._temp = tempfile.TemporaryDirectory(
            prefix="fcc-codex-computer-use-managed."
        )
        temp_root = Path(self._temp.name)
        work_dir = temp_root / "work"
        work_dir.mkdir(mode=0o700)

        self._proc = subprocess.Popen(
            [str(self.paths.codex), *managed_app_server_args()],
            cwd=work_dir,
            env=managed_broker_environment(
                temp_root=temp_root,
                user_home=self.user_home,
                codex_home=self.codex_home,
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        if self._proc.stdout is None or self._proc.stderr is None:
            self.close()
            raise CodexComputerUseError("Codex app-server stdio is unavailable")
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

        try:
            self._request_managed(
                "initialize",
                {
                    "clientInfo": {
                        "name": "fcc_codex_computer_use",
                        "title": "FCC Codex Computer Use",
                        "version": "2",
                    },
                    "capabilities": {
                        "experimentalApi": True,
                        "requestAttestation": False,
                        "mcpServerOpenaiFormElicitation": True,
                    },
                },
                timeout_seconds=15.0,
            )
            self._notify("initialized")
            started = self._request_managed(
                "thread/start",
                managed_thread_start_params(self.paths, work_dir),
                timeout_seconds=30.0,
            )
            thread = started.get("thread")
            thread_id = thread.get("id") if isinstance(thread, Mapping) else None
            if not isinstance(thread_id, str) or not thread_id:
                raise CodexComputerUseError("Codex app-server returned no thread id")
            self._thread_id = thread_id
            self._wait_until_ready()
        except Exception:
            self.close()
            raise

    def call(
        self,
        method: str,
        arguments: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Call one native tool; mutating transport loss is always indeterminate."""

        if method not in COMPUTER_USE_METHODS:
            raise CodexComputerUseError(f"unsupported Computer Use method: {method}")
        if not self.started:
            self.start()
        if self._thread_id is None:
            raise CodexComputerUseError("Codex Computer Use thread is unavailable")
        timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")
        return self._request_managed(
            "mcpServer/tool/call",
            {
                "threadId": self._thread_id,
                "server": SERVER_NAME,
                "tool": method,
                "arguments": dict(arguments),
            },
            timeout_seconds=timeout,
            indeterminate_on_transport_loss=interaction_requires_fresh_state(method),
        )

    def live_readiness_probe(self) -> dict[str, Any]:
        """Run the safest positive native probe without mutating an app."""

        return self.call("list_apps", {})

    def _wait_until_ready(self) -> None:
        if self._thread_id is None:
            raise CodexComputerUseReadinessError("Computer Use thread is unavailable")
        deadline = time.monotonic() + self.readiness_timeout_seconds
        last_names: frozenset[str] = frozenset()
        last_auth: str | None = None
        while time.monotonic() < deadline:
            rows = self._list_mcp_status(deadline)
            server = next(
                (
                    row
                    for row in rows
                    if isinstance(row, Mapping) and row.get("name") == SERVER_NAME
                ),
                None,
            )
            if isinstance(server, Mapping):
                last_names = _tool_names(server)
                auth = server.get("authStatus")
                last_auth = auth if isinstance(auth, str) else None
                if set(COMPUTER_USE_METHODS).issubset(last_names):
                    self._native_tool_names = last_names
                    self._native_auth_status = last_auth
                    return
            time.sleep(READY_POLL_SECONDS)
        missing = sorted(set(COMPUTER_USE_METHODS) - set(last_names))
        raise CodexComputerUseReadinessError(
            "managed Computer Use did not become ready; missing tools: "
            + ", ".join(missing)
        )

    def _list_mcp_status(self, deadline: float) -> list[Mapping[str, Any]]:
        if self._thread_id is None:
            return []
        rows: list[Mapping[str, Any]] = []
        cursor: str | None = None
        for _page in range(MAX_STATUS_PAGES):
            remaining = max(0.1, min(30.0, deadline - time.monotonic()))
            params: dict[str, Any] = {
                "threadId": self._thread_id,
                "detail": "toolsAndAuthOnly",
                "limit": 100,
            }
            if cursor:
                params["cursor"] = cursor
            result = self._request_managed(
                "mcpServerStatus/list",
                params,
                timeout_seconds=remaining,
            )
            data = result.get("data")
            if isinstance(data, list):
                rows.extend(item for item in data if isinstance(item, Mapping))
            next_cursor = result.get("nextCursor")
            cursor = (
                next_cursor if isinstance(next_cursor, str) and next_cursor else None
            )
            if cursor is None:
                break
        return rows

    def _request_managed(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout_seconds: float,
        indeterminate_on_transport_loss: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            self._write({"id": request_id, "method": method, "params": dict(params)})
            deadline = time.monotonic() + timeout_seconds
            while True:
                if self._fatal_error is not None:
                    error = self._fatal_error
                    self.close()
                    raise error
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.close()
                    if indeterminate_on_transport_loss:
                        raise CodexComputerUseIndeterminateError(
                            f"native Computer Use transport timed out after dispatch: {method}"
                        )
                    raise CodexComputerUseError(
                        f"Codex app-server request timed out: {method}"
                    )
                proc = self._proc
                if proc is None or proc.poll() is not None:
                    stderr = "\n".join(self._stderr[-4:])
                    suffix = f": {stderr}" if stderr else ""
                    self.close()
                    if indeterminate_on_transport_loss:
                        raise CodexComputerUseIndeterminateError(
                            f"native Computer Use transport exited after dispatch: {method}{suffix}"
                        )
                    raise CodexComputerUseError(
                        f"Codex app-server exited during {method}{suffix}"
                    )
                try:
                    message = self._messages.get(timeout=min(remaining, 0.25))
                except queue.Empty:
                    continue
                if message.get("id") == request_id:
                    if error := message.get("error"):
                        raise CodexComputerUseError(
                            f"Codex app-server error during {method}: {error}"
                        )
                    result = message.get("result")
                    if not isinstance(result, dict):
                        raise CodexComputerUseError(
                            f"Codex app-server returned invalid {method} result"
                        )
                    return result
                if message.get("id") is not None and message.get("method"):
                    self._handle_server_request(message)

    def _handle_server_request(self, message: Mapping[str, Any]) -> None:
        request_id = message.get("id")
        method = message.get("method")
        if request_id is None or not isinstance(method, str):
            return
        if method != "mcpServer/elicitation/request":
            self._write(
                {
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"FCC does not implement app-server request {method}",
                    },
                }
            )
            return
        params = message.get("params")
        request_params = params if isinstance(params, Mapping) else {}
        self._elicitation_count += 1
        try:
            response = _validate_elicitation_response(
                self.elicitation_handler(request_params)
            )
        except Exception as error:
            response = {"action": "cancel", "content": None, "_meta": None}
            self._fatal_error = CodexComputerUseElicitationError(
                "Computer Use elicitation handler failed closed"
            )
            self._fatal_error.__cause__ = error
        self._write({"id": request_id, "result": response})


__all__ = [
    "CodexComputerUseElicitationError",
    "CodexComputerUseIndeterminateError",
    "CodexComputerUseReadinessError",
    "ManagedCodexComputerUseBroker",
    "managed_app_server_args",
    "managed_broker_environment",
    "managed_launcher",
    "managed_mcp_config",
    "managed_plugin_root",
    "managed_thread_start_params",
]
