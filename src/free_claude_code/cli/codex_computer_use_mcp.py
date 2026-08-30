"""Fixed stdio MCP surface exposing native Codex Computer Use to Claude Code."""

import json
import os
import queue
import signal
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TextIO

from free_claude_code.application.capabilities import (
    Capability,
    CapabilityRouter,
    CapabilityRoutingMode,
    RequiredCapabilitySet,
)
from free_claude_code.application.helpers import (
    ApprovedHelperRegistry,
    HelperExecutionError,
)
from free_claude_code.application.session_policy import (
    build_session_execution_policy,
    parse_allowed_helper_ids,
)
from free_claude_code.config.model_refs import parse_model_name, parse_provider_type
from free_claude_code.config.settings import get_settings
from free_claude_code.runtime.codex_computer_use import (
    COMPUTER_USE_METHODS,
    COMPUTER_USE_TOOL_SPECS,
    CodexComputerUseError,
)
from free_claude_code.runtime.codex_computer_use_helper import (
    CODEX_COMPUTER_USE_HELPER_ID,
    MUTATING_COMPUTER_USE_METHODS,
    CodexComputerUseHelperAdapter,
)

SERVER_NAME = "fcc-codex-computer-use"
SERVER_VERSION = "1"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
CLAUDE_MCP_TOOL_SCHEMA_MAX_BYTES = 16_384
# The catalog is fixed for the lifetime of this process and contains no
# user-specific data. This hint avoids repeated ``tools/list`` round trips;
# it does not change the first schema payload or Claude's deferred loading.
MCP_TOOL_LIST_TTL_MS = 24 * 60 * 60 * 1000
_CONTROLLER_MODEL_ENV = "FCC_CONTROLLER_MODEL_REF"

_READ_ANNOTATIONS = {
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
    "readOnlyHint": True,
}
_ACTION_ANNOTATIONS = {
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": False,
    "readOnlyHint": False,
}


def _accept_native_app_access(_params: Mapping[str, Any]) -> Mapping[str, Any]:
    """Complete the native app-access prompt after explicit helper opt-in."""

    return {"action": "accept", "content": {}, "_meta": None}


def _helper_failure_message(error: HelperExecutionError) -> str:
    """Expose safe runtime diagnostics instead of hiding them behind the helper seam."""

    cause = error.__cause__
    if isinstance(cause, CodexComputerUseError):
        detail = " ".join(str(cause).split())
        if detail:
            return f"Computer Use failed: {detail[:600]}"
    return str(error)


def _decline_native_app_access(_params: Mapping[str, Any]) -> Mapping[str, Any]:
    """Decline native app access with a user-visible permission result."""

    return {"action": "decline", "content": None, "_meta": None}


def _elicitation_handler(
    *,
    approval_mode: str,
    allowed_helper_ids: str,
) -> Callable[[Mapping[str, Any]], Mapping[str, Any]]:
    """Build the app-access handler from the explicit FCC helper policy."""

    helper_allowed = CODEX_COMPUTER_USE_HELPER_ID in set(
        parse_allowed_helper_ids(allowed_helper_ids)
    )
    if helper_allowed and approval_mode == "auto":
        return _accept_native_app_access
    return _decline_native_app_access


@dataclass(slots=True)
class _PendingCall:
    request_id: object
    operation: str
    arguments: dict[str, Any]
    cancelled: threading.Event


def _tool_list() -> list[dict[str, object]]:
    """Return one deterministic Claude-facing tool list for the whole process."""

    tools: list[dict[str, object]] = []
    for spec in COMPUTER_USE_TOOL_SPECS:
        name = str(spec["name"])
        tools.append(
            {
                "name": name,
                "description": str(spec["description"]),
                "inputSchema": spec["input_schema"],
                "annotations": (
                    _ACTION_ANNOTATIONS
                    if name in MUTATING_COMPUTER_USE_METHODS
                    else _READ_ANNOTATIONS
                ),
            }
        )
    return tools


def _serialized_tool_list_bytes(tools: Sequence[Mapping[str, object]]) -> int:
    """Return the deterministic wire size of the Claude-facing tool list."""

    return len(
        json.dumps(
            list(tools),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _validated_tool_list() -> tuple[dict[str, object], ...]:
    """Build the fixed contract and fail closed if it grows unexpectedly."""

    tools = tuple(_tool_list())
    size = _serialized_tool_list_bytes(tools)
    if size > CLAUDE_MCP_TOOL_SCHEMA_MAX_BYTES:
        raise RuntimeError(
            "FCC Computer Use MCP tool schema exceeds its context budget: "
            f"{size} > {CLAUDE_MCP_TOOL_SCHEMA_MAX_BYTES} bytes"
        )
    return tools


CLAUDE_COMPUTER_USE_TOOLS = _validated_tool_list()


def _required_capabilities(operation: str) -> RequiredCapabilitySet:
    capabilities = {Capability.SEMANTIC_MACOS_CONTROL}
    if operation == "get_app_state":
        capabilities.add(Capability.SCREENSHOT_VISION)
    elif operation not in {"list_apps", "get_app_state"}:
        capabilities.add(Capability.PIXEL_COMPUTER_USE)
    return RequiredCapabilitySet(frozenset(capabilities))


def _controller_model_ref() -> str:
    configured = os.environ.get(_CONTROLLER_MODEL_ENV, "").strip()
    if configured:
        return configured
    return get_settings().model


class CodexComputerUseMcpServer:
    """Small MCP server with fixed tools and one bounded helper execution queue."""

    def __init__(self, *, stdin: TextIO, stdout: TextIO) -> None:
        self._stdin = stdin
        self._stdout = stdout
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[str, _PendingCall] = {}
        self._calls: queue.Queue[_PendingCall | None] = queue.Queue()
        self._closed = threading.Event()

        settings = get_settings()
        self._adapter = CodexComputerUseHelperAdapter(
            elicitation_handler=_elicitation_handler(
                approval_mode=settings.computer_use_approval,
                allowed_helper_ids=settings.allowed_helper_ids,
            )
        )
        self._registry = ApprovedHelperRegistry()
        helper = self._adapter.approved_helper()
        self._registry.register(helper)
        self._registry.freeze()

        model_ref = _controller_model_ref()
        self._policy = build_session_execution_policy(
            model_ref,
            self._registry,
            allowed_helper_ids={CODEX_COMPUTER_USE_HELPER_ID},
            routing_mode=CapabilityRoutingMode.SMART_LOCAL,
        )
        self._router = CapabilityRouter(self._policy.routing_policy)
        self._executor = self._policy.helper_executor(self._registry)
        self._controller_provider = parse_provider_type(model_ref)
        self._controller_model = parse_model_name(model_ref)
        self._worker = threading.Thread(
            target=self._call_worker,
            name="fcc-codex-computer-use-mcp",
            daemon=True,
        )
        self._worker.start()

    def serve(self) -> None:
        """Read newline-delimited JSON-RPC until Claude closes stdin."""

        try:
            for raw in self._stdin:
                if self._closed.is_set():
                    break
                line = raw.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    self._write_error(None, -32700, "invalid JSON-RPC payload")
                    continue
                if not isinstance(message, dict):
                    self._write_error(
                        None, -32600, "JSON-RPC message must be an object"
                    )
                    continue
                self._handle_message(message)
        finally:
            self.close()

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        with self._pending_lock:
            for pending in self._pending.values():
                pending.cancelled.set()
        self._adapter.close()
        self._calls.put(None)
        if threading.current_thread() is not self._worker:
            self._worker.join(timeout=1.0)

    def _handle_message(self, message: Mapping[str, Any]) -> None:
        method = message.get("method")
        if not isinstance(method, str):
            self._write_error(message.get("id"), -32600, "JSON-RPC method is required")
            return
        request_id = message.get("id")
        params = message.get("params")
        parameters = params if isinstance(params, Mapping) else {}

        if method == "notifications/initialized":
            return
        if method == "notifications/cancelled":
            self._cancel(parameters.get("requestId"))
            return
        if request_id is None:
            return
        if method == "initialize":
            requested = parameters.get("protocolVersion")
            protocol_version = (
                requested if isinstance(requested, str) else DEFAULT_PROTOCOL_VERSION
            )
            self._write_result(
                request_id,
                {
                    "protocolVersion": protocol_version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            )
            return
        if method == "ping":
            self._write_result(request_id, {})
            return
        if method == "tools/list":
            self._write_result(
                request_id,
                {
                    "tools": list(CLAUDE_COMPUTER_USE_TOOLS),
                    "ttlMs": MCP_TOOL_LIST_TTL_MS,
                    "cacheScope": "public",
                },
            )
            return
        if method == "tools/call":
            self._enqueue_tool_call(request_id, parameters)
            return
        self._write_error(request_id, -32601, f"unsupported MCP method: {method}")

    def _enqueue_tool_call(
        self,
        request_id: object,
        parameters: Mapping[str, Any],
    ) -> None:
        operation = parameters.get("name")
        arguments = parameters.get("arguments", {})
        if not isinstance(operation, str) or operation not in COMPUTER_USE_METHODS:
            self._write_error(request_id, -32602, "unsupported Computer Use tool")
            return
        if not isinstance(arguments, Mapping):
            self._write_error(request_id, -32602, "tool arguments must be an object")
            return
        key = self._request_key(request_id)
        pending = _PendingCall(
            request_id=request_id,
            operation=operation,
            arguments=dict(arguments),
            cancelled=threading.Event(),
        )
        with self._pending_lock:
            if key in self._pending:
                self._write_error(request_id, -32600, "duplicate JSON-RPC request id")
                return
            self._pending[key] = pending
        self._calls.put(pending)

    def _cancel(self, request_id: object) -> None:
        key = self._request_key(request_id)
        with self._pending_lock:
            pending = self._pending.get(key)
        if pending is None:
            return
        pending.cancelled.set()
        self._adapter.close()

    def _call_worker(self) -> None:
        while not self._closed.is_set():
            pending = self._calls.get()
            if pending is None:
                return
            try:
                self._execute_call(pending)
            finally:
                with self._pending_lock:
                    self._pending.pop(self._request_key(pending.request_id), None)

    def _execute_call(self, pending: _PendingCall) -> None:
        if pending.cancelled.is_set():
            self._write_tool_error(pending.request_id, "Computer Use call cancelled")
            return

        required = _required_capabilities(pending.operation)
        try:
            plan = self._router.plan(
                required,
                controller_provider=self._controller_provider,
                controller_model=self._controller_model,
                supported_capabilities=frozenset(),
                known_capabilities=self._registry.resolve(
                    CODEX_COMPUTER_USE_HELPER_ID
                ).capabilities,
                helpers=self._registry.router_helpers(),
            )
            result = self._executor.execute_planned(
                plan,
                helper_id=CODEX_COMPUTER_USE_HELPER_ID,
                operation=pending.operation,
                arguments=pending.arguments,
            )
        except HelperExecutionError as error:
            if pending.cancelled.is_set() and (
                pending.operation in MUTATING_COMPUTER_USE_METHODS
            ):
                self._write_tool_error(
                    pending.request_id,
                    "Computer Use cancellation occurred after a mutating dispatch; "
                    "result is indeterminate and must not be replayed automatically",
                    receipt=error.receipt.as_dict(),
                )
                return
            self._write_tool_error(
                pending.request_id,
                _helper_failure_message(error),
                receipt=error.receipt.as_dict(),
            )
            return
        except Exception as error:
            message = f"Computer Use failed: {type(error).__name__}"
            if pending.cancelled.is_set() and (
                pending.operation in MUTATING_COMPUTER_USE_METHODS
            ):
                message = (
                    "Computer Use cancellation occurred after a mutating dispatch; "
                    "result is indeterminate and must not be replayed automatically"
                )
            self._write_tool_error(pending.request_id, message)
            return

        if pending.cancelled.is_set():
            message = "Computer Use call cancelled"
            if pending.operation in MUTATING_COMPUTER_USE_METHODS:
                message = (
                    "Computer Use cancellation raced a mutating result; state must be "
                    "re-inspected before any further action"
                )
            self._write_tool_error(
                pending.request_id,
                message,
                receipt=result.receipt.as_dict(),
            )
            return
        self._write_native_result(
            pending.request_id,
            result.output,
            receipt=result.receipt.as_dict(),
        )

    def _write_native_result(
        self,
        request_id: object,
        output: Mapping[str, Any],
        *,
        receipt: Mapping[str, object],
    ) -> None:
        content = output.get("content")
        if not isinstance(content, list):
            content = [
                {
                    "type": "text",
                    "text": json.dumps(
                        dict(output),
                        ensure_ascii=True,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                }
            ]
        result: dict[str, object] = {
            "content": content,
            "isError": bool(output.get("isError", False)),
            "_meta": {"fccHelperReceipt": dict(receipt)},
        }
        self._write_result(request_id, result)

    def _write_tool_error(
        self,
        request_id: object,
        message: str,
        *,
        receipt: Mapping[str, object] | None = None,
    ) -> None:
        result: dict[str, object] = {
            "content": [{"type": "text", "text": message}],
            "isError": True,
        }
        if receipt is not None:
            result["_meta"] = {"fccHelperReceipt": dict(receipt)}
        self._write_result(request_id, result)

    def _write_result(self, request_id: object, result: Mapping[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "id": request_id, "result": dict(result)})

    def _write_error(
        self,
        request_id: object,
        code: int,
        message: str,
    ) -> None:
        self._write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message},
            }
        )

    def _write(self, message: Mapping[str, Any]) -> None:
        payload = json.dumps(dict(message), ensure_ascii=True, separators=(",", ":"))
        with self._write_lock:
            self._stdout.write(payload + "\n")
            self._stdout.flush()

    @staticmethod
    def _request_key(request_id: object) -> str:
        return json.dumps(request_id, ensure_ascii=True, sort_keys=True)


def main() -> None:
    server = CodexComputerUseMcpServer(stdin=sys.stdin, stdout=sys.stdout)

    def stop(_signum: int, _frame: object) -> None:
        server.close()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server.serve()


if __name__ == "__main__":
    main()
