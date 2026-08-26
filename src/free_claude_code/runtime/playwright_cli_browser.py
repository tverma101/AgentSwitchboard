"""Thin approved-helper adapter over Microsoft's Playwright CLI.

Harness does not implement browser automation here. It invokes a fixed safe
subset of the maintained ``playwright-cli`` surface and lets the existing #104
helper runtime own policy, timeout, cancellation, output bounds, and receipts.
"""

import json
import math
import os
import re
import shutil
import subprocess
import threading
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from free_claude_code.application.capabilities import Capability
from free_claude_code.application.helpers import ApprovedHelper

PLAYWRIGHT_CLI_HELPER_ID = "playwright-cli-browser"
PLAYWRIGHT_CLI_PROVIDER_FAMILY = "browser"
DEFAULT_PLAYWRIGHT_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_STDOUT_BYTES = 4 * 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024
MAX_TEXT_ARGUMENT = 10_000
MAX_REQUEST_INDEX = 100_000
_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_ATTACH_CHANNELS = frozenset({"chrome", "msedge"})


class PlaywrightCliBrowserError(RuntimeError):
    """The approved Playwright CLI browser adapter rejected or failed a call."""


class PlaywrightCliOperation(StrEnum):
    """Fixed browser surface exposed through the approved-helper seam."""

    STATUS = "status"
    LIST_TABS = "list_tabs"
    OPEN = "open"
    GOTO = "goto"
    SNAPSHOT = "snapshot"
    FIND = "find"
    CLICK = "click"
    FILL = "fill"
    TYPE_TEXT = "type_text"
    PRESS_KEY = "press_key"
    SCROLL = "scroll"
    CONSOLE = "console"
    SCREENSHOT = "screenshot"
    DOWNLOAD = "download"
    CLOSE = "close"


READ_ONLY_PLAYWRIGHT_OPERATIONS = frozenset(
    {
        PlaywrightCliOperation.STATUS.value,
        PlaywrightCliOperation.LIST_TABS.value,
        PlaywrightCliOperation.SNAPSHOT.value,
        PlaywrightCliOperation.FIND.value,
        PlaywrightCliOperation.CONSOLE.value,
    }
)
MUTATING_PLAYWRIGHT_OPERATIONS = (
    frozenset(operation.value for operation in PlaywrightCliOperation)
    - READ_ONLY_PLAYWRIGHT_OPERATIONS
)


class PlaywrightAttachMode(StrEnum):
    """Explicit user-authorized attachment mode for an existing browser."""

    CDP = "cdp"
    EXTENSION = "extension"


def resolve_playwright_cli(explicit: str | Path | None = None) -> Path:
    """Resolve only an already-installed executable; never invoke npm install/npx."""

    if explicit is not None:
        candidate = Path(explicit).expanduser()
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise PlaywrightCliBrowserError(
                f"playwright-cli executable is unavailable: {candidate}"
            )
        return candidate.resolve()

    found = shutil.which("playwright-cli")
    if not found:
        raise PlaywrightCliBrowserError(
            "playwright-cli is not installed; install @playwright/cli explicitly first"
        )
    candidate = Path(found)
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise PlaywrightCliBrowserError("resolved playwright-cli is not executable")
    return candidate.resolve()


def playwright_cli_environment() -> dict[str, str]:
    """Construct a minimal browser environment with update/network probes disabled."""

    env: dict[str, str] = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
        "HOME": str(Path.home()),
        "NO_UPDATE_NOTIFIER": "1",
        "NO_COLOR": "1",
        "CLICOLOR": "0",
    }
    for key in (
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "SHELL",
        "TERM",
        "TMPDIR",
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
    ):
        if value := os.environ.get(key):
            env[key] = value
    return env


def _validate_session_name(value: str) -> str:
    if not isinstance(value, str) or not _SESSION_RE.fullmatch(value):
        raise ValueError(
            "Playwright session name must be 1-64 characters of letters, numbers, _, ., or -"
        )
    return value


def _validate_url(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlaywrightCliBrowserError("browser URL must be a non-empty string")
    url = value.strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise PlaywrightCliBrowserError(
            "browser navigation only permits absolute http/https URLs"
        )
    if parsed.username is not None or parsed.password is not None:
        raise PlaywrightCliBrowserError(
            "browser navigation URL must not contain credentials"
        )
    try:
        _ = parsed.port
    except ValueError as error:
        raise PlaywrightCliBrowserError(
            "browser navigation URL has an invalid port"
        ) from error
    return url


def _required_text(
    arguments: Mapping[str, Any],
    key: str,
    *,
    max_length: int = MAX_TEXT_ARGUMENT,
) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise PlaywrightCliBrowserError(f"browser argument {key!r} must be text")
    if len(value) > max_length:
        raise PlaywrightCliBrowserError(f"browser argument {key!r} exceeds its limit")
    return value


def _optional_int(
    arguments: Mapping[str, Any],
    key: str,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    value = arguments.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlaywrightCliBrowserError(f"browser argument {key!r} must be an integer")
    if value < minimum or value > maximum:
        raise PlaywrightCliBrowserError(
            f"browser argument {key!r} must be between {minimum} and {maximum}"
        )
    return value


def _required_int(
    arguments: Mapping[str, Any],
    key: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = arguments.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlaywrightCliBrowserError(f"browser argument {key!r} must be an integer")
    if value < minimum or value > maximum:
        raise PlaywrightCliBrowserError(
            f"browser argument {key!r} must be between {minimum} and {maximum}"
        )
    return value


def _bounded_number(arguments: Mapping[str, Any], key: str) -> float:
    value = arguments.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PlaywrightCliBrowserError(f"browser argument {key!r} must be numeric")
    number = float(value)
    if not math.isfinite(number) or abs(number) > 100_000:
        raise PlaywrightCliBrowserError(f"browser argument {key!r} exceeds its limit")
    return number


def _validate_cdp_target(value: str) -> str:
    target = value.strip()
    if target in _ATTACH_CHANNELS:
        return target
    parsed = urlsplit(target)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError(
            "existing-browser CDP attachment must use chrome/msedge or a loopback endpoint"
        )
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("existing-browser CDP attachment must not contain credentials")
    try:
        _ = parsed.port
    except ValueError as error:
        raise ValueError(
            "existing-browser CDP attachment has an invalid port"
        ) from error
    return target


def _sanitize_list_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Remove workspace/profile paths from the status result shown to the model."""

    browsers = payload.get("browsers")
    safe_browsers: list[dict[str, Any]] = []
    if isinstance(browsers, list):
        for browser in browsers:
            if not isinstance(browser, Mapping):
                continue
            safe: dict[str, Any] = {}
            for key in (
                "name",
                "status",
                "browserType",
                "headed",
                "persistent",
                "attached",
                "compatible",
                "version",
            ):
                value = browser.get(key)
                if isinstance(value, str | bool) or value is None:
                    safe[key] = value
            safe_browsers.append(safe)
    return {"browsers": safe_browsers}


def _sanitize_tab_list_text(value: object) -> object:
    """Hide query strings, fragments, and URL credentials in tab inventory."""

    if not isinstance(value, str):
        return value
    sanitized: list[str] = []
    cursor = 0
    while cursor < len(value):
        start = value.find("http://", cursor)
        https_start = value.find("https://", cursor)
        starts = [position for position in (start, https_start) if position >= 0]
        if not starts:
            sanitized.append(value[cursor:])
            break
        start = min(starts)
        sanitized.append(value[cursor:start])
        end = start
        while end < len(value) and value[end] not in " )]}>\n\r\t":
            end += 1
        raw_url = value[start:end]
        try:
            parsed = urlsplit(raw_url)
            if not parsed.hostname:
                raise ValueError
            host = parsed.hostname
            try:
                port = parsed.port
            except ValueError:
                port = None
            netloc = host if port is None else f"{host}:{port}"
            safe_url = urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
        except ValueError:
            safe_url = "[redacted-url]"
        sanitized.append(safe_url)
        cursor = end
    return "".join(sanitized)


def _sanitize_payload(
    operation: PlaywrightCliOperation, payload: Any
) -> dict[str, Any]:
    if operation is PlaywrightCliOperation.STATUS and isinstance(payload, Mapping):
        return _sanitize_list_payload(payload)
    if isinstance(payload, Mapping):
        result = dict(payload)
        # Process ids and attach endpoints are control-plane metadata, not page content.
        result.pop("pid", None)
        result.pop("endpoint", None)
        if operation is PlaywrightCliOperation.LIST_TABS and "result" in result:
            result["result"] = _sanitize_tab_list_text(result["result"])
        return result
    if operation is PlaywrightCliOperation.LIST_TABS:
        return {"result": _sanitize_tab_list_text(payload)}
    return {"result": payload}


class PlaywrightCliBrowserAdapter:
    """Invoke an approved subset of the official token-efficient browser CLI."""

    def __init__(
        self,
        *,
        session_name: str = "fcc-browser",
        executable: str | Path | None = None,
        headed: bool = False,
        allow_existing_session: bool = False,
        attach_mode: PlaywrightAttachMode | str | None = None,
        attach_target: str | None = None,
    ) -> None:
        self.session_name = _validate_session_name(session_name)
        self._explicit_executable = executable
        self.headed = bool(headed)
        self.allow_existing_session = allow_existing_session
        self.attach_mode = (
            PlaywrightAttachMode(attach_mode) if attach_mode is not None else None
        )
        self.attach_target = attach_target
        self._attached = False
        self._lock = threading.Lock()

        if (self.attach_mode is None) != (attach_target is None):
            raise ValueError("attach_mode and attach_target must be supplied together")
        if self.attach_mode is not None and not allow_existing_session:
            raise ValueError("existing browser attachment requires explicit opt-in")
        if self.attach_mode is PlaywrightAttachMode.CDP and attach_target is not None:
            self.attach_target = _validate_cdp_target(attach_target)
        if (
            self.attach_mode is PlaywrightAttachMode.EXTENSION
            and attach_target not in _ATTACH_CHANNELS
        ):
            raise ValueError("extension attachment supports only chrome or msedge")

    def approved_helper(
        self,
        *,
        max_output_bytes: int = DEFAULT_PLAYWRIGHT_OUTPUT_BYTES,
    ) -> ApprovedHelper:
        """Return deterministic metadata for the existing #30/#104 route."""

        return ApprovedHelper(
            helper_id=PLAYWRIGHT_CLI_HELPER_ID,
            provider_family=PLAYWRIGHT_CLI_PROVIDER_FAMILY,
            capabilities=frozenset({Capability.SEMANTIC_BROWSER_CONTROL}),
            execute=self.execute,
            local=True,
            billable=False,
            max_output_bytes=max_output_bytes,
            mutating_operations=MUTATING_PLAYWRIGHT_OPERATIONS,
        )

    def execute(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        cancel_event: threading.Event,
    ) -> Mapping[str, Any]:
        """Execute one fixed Playwright CLI operation without shell or dynamic code."""

        try:
            selected = PlaywrightCliOperation(operation)
        except ValueError as error:
            supported = ", ".join(item.value for item in PlaywrightCliOperation)
            raise PlaywrightCliBrowserError(
                f"unsupported browser helper operation; supported: {supported}"
            ) from error
        if cancel_event.is_set():
            raise PlaywrightCliBrowserError("browser helper cancelled before dispatch")

        with self._lock:
            if self.attach_mode is not None and not self._attached:
                if selected is PlaywrightCliOperation.OPEN:
                    raise PlaywrightCliBrowserError(
                        "attached browser helpers cannot open a separate browser"
                    )
                self._attach_existing(cancel_event)

            command = self._command(selected, arguments)
            payload = self._run(command, cancel_event)
            if selected is PlaywrightCliOperation.CLOSE:
                self._attached = False
            return _sanitize_payload(selected, payload)

    def _attach_existing(self, cancel_event: threading.Event) -> None:
        if self.attach_mode is None or self.attach_target is None:
            return
        if not self.allow_existing_session:
            raise PlaywrightCliBrowserError(
                "existing browser attachment is not authorized"
            )
        if self.attach_mode is PlaywrightAttachMode.CDP:
            args = ["attach", f"--cdp={self.attach_target}"]
        else:
            args = ["attach", f"--extension={self.attach_target}"]
        self._run(args, cancel_event)
        self._attached = True

    def _command(
        self,
        operation: PlaywrightCliOperation,
        arguments: Mapping[str, Any],
    ) -> list[str]:
        if operation is PlaywrightCliOperation.STATUS:
            return ["list"]
        if operation is PlaywrightCliOperation.LIST_TABS:
            return ["tab-list"]
        if operation is PlaywrightCliOperation.OPEN:
            if self.attach_mode is not None:
                raise PlaywrightCliBrowserError(
                    "attached browser helpers cannot open a separate browser"
                )
            args = ["open"]
            url = arguments.get("url")
            if url is not None:
                args.append(_validate_url(url))
            if self.headed:
                args.append("--headed")
            return args
        if operation is PlaywrightCliOperation.GOTO:
            return ["goto", _validate_url(arguments.get("url"))]
        if operation is PlaywrightCliOperation.SNAPSHOT:
            args = ["snapshot"]
            target = arguments.get("target")
            if target is not None:
                if not isinstance(target, str) or not target or len(target) > 1000:
                    raise PlaywrightCliBrowserError("snapshot target is invalid")
                args.append(target)
            if depth := _optional_int(arguments, "depth", minimum=1, maximum=20):
                args.append(f"--depth={depth}")
            return args
        if operation is PlaywrightCliOperation.FIND:
            pattern = _required_text(arguments, "text", max_length=2000)
            if arguments.get("regex") is True:
                return ["find", "--regex", pattern]
            return ["find", pattern]
        if operation is PlaywrightCliOperation.CLICK:
            target = _required_text(arguments, "target", max_length=1000)
            args = ["click", target]
            button = arguments.get("button")
            if button is not None:
                if button not in {"left", "right", "middle"}:
                    raise PlaywrightCliBrowserError("click button is invalid")
                args.append(str(button))
            return args
        if operation is PlaywrightCliOperation.FILL:
            target = _required_text(arguments, "target", max_length=1000)
            text = _required_text(arguments, "text")
            args = ["fill", target, text]
            if arguments.get("submit") is True:
                args.append("--submit")
            return args
        if operation is PlaywrightCliOperation.TYPE_TEXT:
            return ["type", _required_text(arguments, "text")]
        if operation is PlaywrightCliOperation.PRESS_KEY:
            return ["press", _required_text(arguments, "key", max_length=100)]
        if operation is PlaywrightCliOperation.SCROLL:
            delta_x = _bounded_number(arguments, "delta_x")
            delta_y = _bounded_number(arguments, "delta_y")
            return ["mousewheel", str(delta_x), str(delta_y)]
        if operation is PlaywrightCliOperation.CONSOLE:
            level = arguments.get("min_level")
            if level is None:
                return ["console"]
            if level not in {"error", "warning", "info", "debug"}:
                raise PlaywrightCliBrowserError("console level is invalid")
            return ["console", str(level)]
        if operation is PlaywrightCliOperation.SCREENSHOT:
            args = ["screenshot"]
            target = arguments.get("target")
            if target is not None:
                if not isinstance(target, str) or not target or len(target) > 1000:
                    raise PlaywrightCliBrowserError("screenshot target is invalid")
                args.append(target)
            if arguments.get("hires") is True:
                args.append("--hires")
            return args
        if operation is PlaywrightCliOperation.DOWNLOAD:
            request_index = _required_int(
                arguments,
                "request_index",
                minimum=1,
                maximum=MAX_REQUEST_INDEX,
            )
            return ["response-body", str(request_index)]
        if operation is PlaywrightCliOperation.CLOSE:
            return ["detach"] if self.attach_mode is not None else ["close"]
        raise AssertionError(f"unhandled browser operation: {operation}")

    def _run(
        self,
        command_args: list[str],
        cancel_event: threading.Event,
    ) -> Any:
        executable = resolve_playwright_cli(self._explicit_executable)
        argv = [
            str(executable),
            "--json",
            f"-s={self.session_name}",
            *command_args,
        ]
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=playwright_cli_environment(),
            shell=False,
            start_new_session=True,
        )
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=0.05)
                break
            except subprocess.TimeoutExpired:
                if not cancel_event.is_set():
                    continue
                proc.terminate()
                try:
                    stdout, stderr = proc.communicate(timeout=0.5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout, stderr = proc.communicate(timeout=0.5)
                raise PlaywrightCliBrowserError("browser helper cancelled") from None

        if len(stdout.encode("utf-8", errors="replace")) > MAX_STDOUT_BYTES:
            raise PlaywrightCliBrowserError(
                "playwright-cli stdout exceeded the safety bound"
            )
        if len(stderr.encode("utf-8", errors="replace")) > MAX_STDERR_BYTES:
            stderr = stderr[-MAX_STDERR_BYTES:]
        try:
            payload = json.loads(stdout) if stdout.strip() else {}
        except json.JSONDecodeError as error:
            raise PlaywrightCliBrowserError(
                "playwright-cli returned invalid JSON"
            ) from error
        if proc.returncode != 0:
            detail = ""
            if isinstance(payload, Mapping) and isinstance(payload.get("error"), str):
                detail = f": {payload['error']}"
            elif stderr.strip():
                detail = ": playwright-cli reported an error"
            raise PlaywrightCliBrowserError(f"playwright-cli command failed{detail}")
        if isinstance(payload, Mapping) and payload.get("isError") is True:
            detail = payload.get("error")
            raise PlaywrightCliBrowserError(
                f"playwright-cli command failed: {detail if isinstance(detail, str) else 'unknown error'}"
            )
        return payload


__all__ = [
    "MUTATING_PLAYWRIGHT_OPERATIONS",
    "PLAYWRIGHT_CLI_HELPER_ID",
    "PLAYWRIGHT_CLI_PROVIDER_FAMILY",
    "READ_ONLY_PLAYWRIGHT_OPERATIONS",
    "PlaywrightAttachMode",
    "PlaywrightCliBrowserAdapter",
    "PlaywrightCliBrowserError",
    "PlaywrightCliOperation",
    "playwright_cli_environment",
    "resolve_playwright_cli",
]
