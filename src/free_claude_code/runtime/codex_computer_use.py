"""Direct bridge to OpenAI's signed Codex Computer Use host.

Transport adapted from tmustier/codex-computer-use-mcp @ e90efa7b and
manaflow-ai/codex-cua @ 3073c1f8 (both MIT). Harness does not reimplement
macOS automation: it asks signed Codex ``app-server`` to dispatch the signed
``computer-use`` MCP tools, with model paths disabled.
"""

import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

OPENAI_TEAM_ID = "2DC432GLL2"
SERVER_NAME = "computer-use"
DEFAULT_TIMEOUT_SECONDS = 120.0
CODEX_APP_CANDIDATES = (
    Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
    Path("/Applications/Codex.app/Contents/Resources/codex"),
)
CLIENT_RELATIVE_PATH = Path(
    "Contents/SharedSupport/SkyComputerUseClient.app/Contents/MacOS/"
    "SkyComputerUseClient"
)

COMPUTER_USE_METHODS = (
    "list_apps",
    "get_app_state",
    "click",
    "perform_secondary_action",
    "set_value",
    "select_text",
    "scroll",
    "drag",
    "press_key",
    "type_text",
)
_INTERACTION_METHODS = frozenset(COMPUTER_USE_METHODS[2:])

_APP = {"type": "string"}
_STRING = {"type": "string"}
_NUMBER = {"type": "number"}
_TOOL_DEFS: tuple[tuple[str, str, dict[str, Any], tuple[str, ...]], ...] = (
    ("list_apps", "List running and recently used apps on this computer.", {}, ()),
    (
        "get_app_state",
        "Return an app key-window screenshot and accessibility tree. Call once "
        "per assistant turn before interacting with that app.",
        {"app": _APP},
        ("app",),
    ),
    (
        "click",
        "Click an element index or screenshot pixel coordinates.",
        {
            "app": _APP,
            "click_count": {"type": "integer"},
            "element_index": _STRING,
            "mouse_button": {"type": "string", "enum": ["left", "right", "middle"]},
            "x": _NUMBER,
            "y": _NUMBER,
        },
        ("app",),
    ),
    (
        "perform_secondary_action",
        "Invoke a secondary accessibility action exposed by an element.",
        {"app": _APP, "element_index": _STRING, "action": _STRING},
        ("app", "element_index", "action"),
    ),
    (
        "set_value",
        "Set the value of a settable accessibility element.",
        {"app": _APP, "element_index": _STRING, "value": _STRING},
        ("app", "element_index", "value"),
    ),
    (
        "select_text",
        "Select text or place the cursor before or after matching text.",
        {
            "app": _APP,
            "element_index": _STRING,
            "text": _STRING,
            "prefix": _STRING,
            "selection": {
                "type": "string",
                "enum": ["text", "cursor_before", "cursor_after"],
            },
            "suffix": _STRING,
        },
        ("app", "element_index", "text"),
    ),
    (
        "scroll",
        "Scroll an element in a direction by a number of pages.",
        {
            "app": _APP,
            "element_index": _STRING,
            "direction": _STRING,
            "pages": _NUMBER,
        },
        ("app", "element_index", "direction"),
    ),
    (
        "drag",
        "Drag from one screenshot coordinate to another.",
        {
            "app": _APP,
            "from_x": _NUMBER,
            "from_y": _NUMBER,
            "to_x": _NUMBER,
            "to_y": _NUMBER,
        },
        ("app", "from_x", "from_y", "to_x", "to_y"),
    ),
    (
        "press_key",
        "Press a keyboard key or key combination in an app.",
        {"app": _APP, "key": _STRING},
        ("app", "key"),
    ),
    (
        "type_text",
        "Type literal text into an app.",
        {"app": _APP, "text": _STRING},
        ("app", "text"),
    ),
)


def _build_tool_specs() -> tuple[dict[str, Any], ...]:
    specs: list[dict[str, Any]] = []
    for name, description, properties, required in _TOOL_DEFS:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": True,
        }
        if required:
            schema["required"] = list(required)
        specs.append({"name": name, "description": description, "input_schema": schema})
    return tuple(specs)


# Runtime discovery never mutates this Luna-facing prefix contract.
COMPUTER_USE_TOOL_SPECS = _build_tool_specs()


class CodexComputerUseError(RuntimeError):
    """Raised when the official Computer Use bridge cannot fail safely."""


@dataclass(frozen=True, slots=True)
class CodexComputerUsePaths:
    """Verified signed executables used by the direct bridge."""

    codex: Path
    app: Path
    client: Path


def tool_contract_bytes() -> bytes:
    """Return deterministic bytes for Luna cache/economic receipts."""

    return json.dumps(
        COMPUTER_USE_TOOL_SPECS,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def tool_contract_hash() -> str:
    return sha256(tool_contract_bytes()).hexdigest()


def _run_codesign(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _verify_openai_binary(path: Path) -> None:
    if not path.is_file() or not os.access(path, os.X_OK):
        raise CodexComputerUseError(f"required executable is missing: {path}")
    verify = _run_codesign(["/usr/bin/codesign", "--verify", "--strict", str(path)])
    if verify.returncode != 0:
        raise CodexComputerUseError(f"signature verification failed: {path.name}")
    details = _run_codesign(["/usr/bin/codesign", "-dv", "--verbose=2", str(path)])
    marker = f"TeamIdentifier={OPENAI_TEAM_ID}"
    output = f"{details.stdout}\n{details.stderr}"
    if details.returncode != 0 or marker not in output.splitlines():
        raise CodexComputerUseError(
            f"{path.name} is not signed by the expected OpenAI team"
        )


def _client_app_candidates(home: Path) -> tuple[Path, ...]:
    user_root = home / ".codex"
    candidates = [
        user_root / "computer-use" / "Codex Computer Use.app",
        user_root
        / "plugins"
        / "openai-bundled"
        / "plugins"
        / "computer-use"
        / "Codex Computer Use.app",
    ]
    candidates.extend(
        codex.parent
        / "plugins"
        / "openai-bundled"
        / "plugins"
        / "computer-use"
        / "Codex Computer Use.app"
        for codex in CODEX_APP_CANDIDATES
    )
    return tuple(candidates)


def resolve_official_computer_use(
    *,
    home: Path | None = None,
    codex_override: Path | None = None,
) -> CodexComputerUsePaths:
    """Resolve and verify only signed OpenAI Codex/Computer Use binaries."""

    if sys.platform != "darwin":
        raise CodexComputerUseError("Codex Computer Use is supported only on macOS")

    codex_candidates: list[Path] = []
    if codex_override is not None:
        codex_candidates.append(codex_override)
    codex_candidates.extend(CODEX_APP_CANDIDATES)
    if discovered := shutil.which("codex"):
        codex_candidates.append(Path(discovered))

    codex: Path | None = None
    for candidate in codex_candidates:
        if not candidate.is_file():
            continue
        canonical = candidate.resolve()
        _verify_openai_binary(canonical)
        codex = canonical
        break
    if codex is None:
        raise CodexComputerUseError("signed Codex executable was not found")

    for app in _client_app_candidates(home or Path.home()):
        client = app / CLIENT_RELATIVE_PATH
        if not client.is_file():
            continue
        canonical_app = app.resolve()
        canonical_client = client.resolve()
        _verify_openai_binary(canonical_client)
        return CodexComputerUsePaths(codex, canonical_app, canonical_client)
    raise CodexComputerUseError("signed Codex Computer Use client was not found")


def _broker_environment(temp_root: Path, codex_home: Path) -> dict[str, str]:
    env = {
        "HOME": str(temp_root),
        "CODEX_HOME": str(codex_home),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "TMPDIR": str(temp_root),
        "NO_COLOR": "1",
        "CLICOLOR": "0",
    }
    for key in ("USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "SHELL", "TERM"):
        if value := os.environ.get(key):
            env[key] = value
    return env


def _app_server_args(paths: CodexComputerUsePaths, work_dir: Path) -> list[str]:
    disabled_provider = (
        '{ name = "Direct dispatch disabled provider", '
        'base_url = "http://127.0.0.1:9/v1", wire_api = "responses", '
        "request_max_retries = 0, stream_max_retries = 0, "
        "supports_websockets = false, requires_openai_auth = false }"
    )
    overrides = (
        'model_provider="direct_disabled"',
        'model="direct-disabled"',
        f"model_providers.direct_disabled={disabled_provider}",
        "features.shell_tool=false",
        "features.unified_exec=false",
        "features.multi_agent=false",
        "features.memories=false",
        "memories.use_memories=false",
        "memories.generate_memories=false",
        "features.remote_plugin=false",
        "features.plugins=false",
        "features.hooks=false",
        "analytics.enabled=false",
        'otel.exporter="none"',
        'web_search="disabled"',
        'history.persistence="none"',
        f"mcp_servers.{SERVER_NAME}.enabled=true",
        f"mcp_servers.{SERVER_NAME}.command={json.dumps(str(paths.client))}",
        f'mcp_servers.{SERVER_NAME}.args=["mcp"]',
        f"mcp_servers.{SERVER_NAME}.cwd={json.dumps(str(work_dir))}",
        f"mcp_servers.{SERVER_NAME}.startup_timeout_sec=30",
        f"mcp_servers.{SERVER_NAME}.tool_timeout_sec=120",
    )
    args: list[str] = []
    for override in overrides:
        args.extend(("-c", override))
    return [*args, "app-server", "--stdio"]


class CodexComputerUseBroker:
    """Warm zero-model-turn session over Codex app-server stdio."""

    def __init__(
        self,
        paths: CodexComputerUsePaths,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.paths = paths
        self.timeout_seconds = timeout_seconds
        self._proc: subprocess.Popen[str] | None = None
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr: list[str] = []
        self._next_id = 0
        self._thread_id: str | None = None
        self._lock = threading.Lock()
        self._temp: tempfile.TemporaryDirectory[str] | None = None
        self._fatal_error: CodexComputerUseError | None = None

    @property
    def started(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if self.started:
            return
        self._temp = tempfile.TemporaryDirectory(prefix="fcc-codex-computer-use.")
        temp_root = Path(self._temp.name)
        codex_home = temp_root / "codex-home"
        work_dir = temp_root / "work"
        codex_home.mkdir(mode=0o700)
        work_dir.mkdir(mode=0o700)
        config_path = codex_home / "config.toml"
        config_path.write_text("", encoding="utf-8")
        os.chmod(config_path, 0o600)

        self._proc = subprocess.Popen(
            [str(self.paths.codex), *_app_server_args(self.paths, work_dir)],
            cwd=work_dir,
            env=_broker_environment(temp_root, codex_home),
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

        self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "fcc_codex_computer_use",
                    "title": "FCC Codex Computer Use",
                    "version": "1",
                },
                "capabilities": {},
            },
            timeout_seconds=15.0,
        )
        self._notify("initialized", {})
        started = self._request(
            "thread/start",
            {
                "cwd": str(work_dir),
                "approvalPolicy": "never",
                "sandbox": "danger-full-access",
                "ephemeral": True,
                "serviceName": "fcc_codex_computer_use",
            },
            timeout_seconds=30.0,
        )
        thread = started.get("thread")
        thread_id = thread.get("id") if isinstance(thread, Mapping) else None
        if not isinstance(thread_id, str):
            self.close()
            raise CodexComputerUseError("Codex app-server returned no thread id")
        self._thread_id = thread_id

    def call(
        self,
        method: str,
        arguments: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Call one official Computer Use tool without a Codex model turn."""

        if method not in COMPUTER_USE_METHODS:
            raise CodexComputerUseError(f"unsupported Computer Use method: {method}")
        if not self.started:
            self.start()
        if self._thread_id is None:
            raise CodexComputerUseError("Codex Computer Use thread is unavailable")
        return self._request(
            "mcpServer/tool/call",
            {
                "threadId": self._thread_id,
                "server": SERVER_NAME,
                "tool": method,
                "arguments": dict(arguments),
            },
            timeout_seconds=timeout_seconds or self.timeout_seconds,
        )

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        self._thread_id = None
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError, PermissionError:
                proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError, PermissionError:
                    proc.kill()
                proc.wait(timeout=2)
        if self._temp is not None:
            self._temp.cleanup()
            self._temp = None

    def __enter__(self) -> CodexComputerUseBroker:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        self.close()

    def _read_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for raw in proc.stdout:
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                self._fatal_error = CodexComputerUseError(
                    "Codex app-server emitted malformed JSON"
                )
                continue
            if not isinstance(message, dict):
                continue
            method = message.get("method")
            if isinstance(method, str) and method.startswith(("turn/", "item/")):
                self._fatal_error = CodexComputerUseError(
                    "Codex model-turn activity appeared during direct Computer Use"
                )
            self._messages.put(message)

    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for raw in proc.stderr:
            if len(self._stderr) < 64:
                self._stderr.append(raw.rstrip())

    def _notify(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
    ) -> None:
        self._write({"method": method, "params": dict(params or {})})

    def _write(self, message: Mapping[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise CodexComputerUseError("Codex app-server is not writable")
        proc.stdin.write(json.dumps(dict(message), separators=(",", ":")) + "\n")
        proc.stdin.flush()

    def _request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout_seconds: float,
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
                    raise CodexComputerUseError(
                        f"Codex app-server request timed out: {method}"
                    )
                proc = self._proc
                if proc is None or proc.poll() is not None:
                    stderr = "\n".join(self._stderr[-4:])
                    suffix = f": {stderr}" if stderr else ""
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
                    # Fail closed on host prompts. A separate policy adapter may decide
                    # whether an elicitation can be approved.
                    self._write({"id": message["id"], "result": {"action": "cancel"}})


def interaction_requires_fresh_state(method: str) -> bool:
    return method in _INTERACTION_METHODS


__all__ = [
    "COMPUTER_USE_METHODS",
    "COMPUTER_USE_TOOL_SPECS",
    "CodexComputerUseBroker",
    "CodexComputerUseError",
    "CodexComputerUsePaths",
    "interaction_requires_fresh_state",
    "resolve_official_computer_use",
    "tool_contract_bytes",
    "tool_contract_hash",
]
