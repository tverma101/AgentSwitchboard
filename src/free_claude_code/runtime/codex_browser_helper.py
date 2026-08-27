"""Approved-helper adapter for the installed Codex browser plugin."""

import json
import os
import shutil
import subprocess
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from free_claude_code.application.capabilities import Capability
from free_claude_code.application.helpers import ApprovedHelper

CODEX_BROWSER_HELPER_ID = "codex-browser"
CODEX_BROWSER_PROVIDER_FAMILY = "browser"
DEFAULT_BROWSER_OUTPUT_BYTES = 24 * 1024 * 1024
BROWSER_FAMILIES = frozenset({"chrome", "edge"})
BROWSER_OPERATIONS = frozenset(
    {
        "list_tabs",
        "claim_tab",
        "new_tab",
        "selected_tab",
        "tab_info",
        "goto",
        "snapshot",
        "click",
        "set_value",
        "type_text",
        "press_key",
        "scroll",
        "screenshot",
        "reload",
        "back",
        "forward",
        "mark_handoff",
        "mark_deliverable",
        "close_tab",
    }
)
READ_ONLY_BROWSER_OPERATIONS = frozenset(
    {"list_tabs", "selected_tab", "tab_info", "snapshot", "screenshot"}
)
MUTATING_BROWSER_OPERATIONS = BROWSER_OPERATIONS - READ_ONLY_BROWSER_OPERATIONS
_ENV_ALLOWLIST = frozenset(
    {
        "CODEX_HOME",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "NODE_PATH",
        "PATH",
        "SHELL",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USER",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_RUNTIME_DIR",
    }
)


class CodexBrowserHelperError(RuntimeError):
    """The installed Codex browser bridge could not serve one bounded call."""


class CodexBrowserHelperAdapter:
    """Own one warm Node bridge to Codex's installed browser plugin."""

    def __init__(
        self,
        *,
        family: str = "chrome",
        plugin_root: Path | None = None,
        session_id: str = "fcc-browser",
    ) -> None:
        if family not in BROWSER_FAMILIES:
            raise ValueError("browser family must be chrome or edge")
        if plugin_root is not None and not plugin_root.is_absolute():
            raise ValueError("Codex browser plugin root must be absolute")
        if not session_id.strip():
            raise ValueError("session_id is required")
        self._family = family
        self._plugin_root = plugin_root
        self._session_id = session_id
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._next_id = 1

    def close(self) -> None:
        """Terminate only the bridge process owned by this adapter."""

        with self._process_lock:
            process = self._process
            self._process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=0.5)
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()

    def execute(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        cancel_event: threading.Event,
    ) -> Mapping[str, Any]:
        """Execute one allowlisted browser operation through the installed plugin."""

        if operation not in BROWSER_OPERATIONS:
            raise CodexBrowserHelperError(
                f"unsupported Codex browser helper operation: {operation}"
            )
        if cancel_event.is_set():
            raise CodexBrowserHelperError(
                "Codex browser helper cancelled before dispatch"
            )

        with self._request_lock:
            process = self._get_process()
            finished = threading.Event()

            def cancel_watcher() -> None:
                while not finished.wait(timeout=0.05):
                    if cancel_event.is_set():
                        self.close()
                        return

            watcher = threading.Thread(
                target=cancel_watcher,
                name="fcc-codex-browser-cancel",
                daemon=True,
            )
            watcher.start()
            try:
                return self._call(process, operation, arguments)
            finally:
                finished.set()
                watcher.join(timeout=0.2)

    def approved_helper(
        self,
        *,
        max_output_bytes: int = DEFAULT_BROWSER_OUTPUT_BYTES,
    ) -> ApprovedHelper:
        """Return deterministic #30/#104 metadata for this local helper."""

        return ApprovedHelper(
            helper_id=CODEX_BROWSER_HELPER_ID,
            provider_family=CODEX_BROWSER_PROVIDER_FAMILY,
            capabilities=frozenset(
                {Capability.SEMANTIC_BROWSER_CONTROL, Capability.SCREENSHOT_VISION}
            ),
            execute=self.execute,
            local=True,
            billable=False,
            max_output_bytes=max_output_bytes,
            mutating_operations=MUTATING_BROWSER_OPERATIONS,
        )

    def _get_process(self) -> subprocess.Popen[str]:
        with self._process_lock:
            process = self._process
            if process is not None and process.poll() is None:
                return process

            node = shutil.which("node")
            if node is None:
                raise CodexBrowserHelperError(
                    "Node.js is required for Codex browser use"
                )
            script = Path(__file__).with_name("codex_browser_helper.mjs")
            if not script.is_file():
                raise CodexBrowserHelperError(
                    "packaged Codex browser helper is missing"
                )

            process = subprocess.Popen(
                [node, str(script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=self._child_environment(),
            )
            if process.stdin is None or process.stdout is None:
                process.kill()
                raise CodexBrowserHelperError(
                    "failed to open Codex browser helper pipes"
                )
            self._process = process
            return process

    def _call(
        self,
        process: subprocess.Popen[str],
        operation: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        if process.stdin is None or process.stdout is None:
            raise CodexBrowserHelperError("Codex browser helper pipes are unavailable")
        request_id = self._next_id
        self._next_id += 1
        request = {
            "id": request_id,
            "operation": operation,
            "arguments": dict(arguments),
        }
        try:
            encoded = json.dumps(request, separators=(",", ":"), ensure_ascii=False)
        except (TypeError, ValueError) as error:
            raise CodexBrowserHelperError(
                "browser arguments must be JSON-compatible"
            ) from error

        try:
            process.stdin.write(encoded + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
        except (BrokenPipeError, OSError) as error:
            self.close()
            raise CodexBrowserHelperError(
                "Codex browser helper transport failed"
            ) from error
        if not line:
            self.close()
            raise CodexBrowserHelperError(
                "Codex browser helper exited without a response"
            )
        try:
            response = json.loads(line)
        except json.JSONDecodeError as error:
            self.close()
            raise CodexBrowserHelperError(
                "Codex browser helper returned invalid JSON"
            ) from error
        if not isinstance(response, Mapping) or response.get("id") != request_id:
            self.close()
            raise CodexBrowserHelperError(
                "Codex browser helper response correlation failed"
            )
        if response.get("ok") is not True:
            raise CodexBrowserHelperError("Codex browser operation failed")
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise CodexBrowserHelperError(
                "Codex browser helper returned non-object output"
            )
        return dict(result)

    def _child_environment(self) -> dict[str, str]:
        environment = {
            key: value for key, value in os.environ.items() if key in _ENV_ALLOWLIST
        }
        environment["FCC_CODEX_BROWSER_FAMILY"] = self._family
        environment["FCC_CODEX_BROWSER_SESSION_ID"] = self._session_id
        if self._plugin_root is not None:
            environment["FCC_CODEX_BROWSER_PLUGIN_ROOT"] = str(self._plugin_root)
        return environment


__all__ = [
    "BROWSER_FAMILIES",
    "BROWSER_OPERATIONS",
    "CODEX_BROWSER_HELPER_ID",
    "CODEX_BROWSER_PROVIDER_FAMILY",
    "MUTATING_BROWSER_OPERATIONS",
    "READ_ONLY_BROWSER_OPERATIONS",
    "CodexBrowserHelperAdapter",
    "CodexBrowserHelperError",
]
