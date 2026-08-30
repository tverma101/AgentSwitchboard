"""Contract tests for Claude's fixed Codex Computer Use MCP surface."""

import io
import json
import threading
from typing import Any, cast

import pytest

from free_claude_code.application.helpers import (
    HelperExecutionError,
    HelperExecutionReceipt,
    HelperExecutionResult,
    HelperExecutionStatus,
)
from free_claude_code.cli.codex_computer_use_mcp import (
    CLAUDE_COMPUTER_USE_TOOLS,
    CLAUDE_MCP_TOOL_SCHEMA_MAX_BYTES,
    MCP_TOOL_LIST_TTL_MS,
    CodexComputerUseMcpServer,
    _elicitation_handler,
    _PendingCall,
    _serialized_tool_list_bytes,
)
from free_claude_code.runtime.codex_computer_use import (
    COMPUTER_USE_METHODS,
    CodexComputerUseError,
)


def _server(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[CodexComputerUseMcpServer, io.StringIO]:
    monkeypatch.setenv(
        "FCC_CONTROLLER_MODEL_REF",
        "opencode_go/muse-spark-1.2-contributor",
    )
    output = io.StringIO()
    server = CodexComputerUseMcpServer(stdin=io.StringIO(), stdout=output)
    return server, output


def _messages(output: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.getvalue().splitlines() if line]


def _success_result(operation: str) -> HelperExecutionResult:
    return HelperExecutionResult(
        output={"content": [{"type": "text", "text": f"ok:{operation}"}]},
        receipt=HelperExecutionReceipt(
            helper_id="codex-computer-use",
            provider_family="computer",
            operation=operation,
            status=HelperExecutionStatus.SUCCESS,
            duration_ms=3,
            attempts=1,
            local=True,
            billable=False,
            output_bytes=32,
        ),
    )


def _annotations(tool: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], tool["annotations"])


def test_tool_list_is_fixed_order_and_has_native_read_action_annotations() -> None:
    assert [tool["name"] for tool in CLAUDE_COMPUTER_USE_TOOLS] == list(
        COMPUTER_USE_METHODS
    )
    rendered = json.dumps(CLAUDE_COMPUTER_USE_TOOLS, sort_keys=True)
    assert "/Applications/" not in rendered
    assert "/Users/" not in rendered
    assert "threadId" not in rendered
    assert "OPENAI_API_KEY" not in rendered

    by_name = {str(tool["name"]): tool for tool in CLAUDE_COMPUTER_USE_TOOLS}
    assert _annotations(by_name["list_apps"])["readOnlyHint"] is True
    assert _annotations(by_name["get_app_state"])["readOnlyHint"] is True
    assert _annotations(by_name["click"])["readOnlyHint"] is False
    assert _annotations(by_name["type_text"])["idempotentHint"] is False


def test_tool_schema_stays_within_its_context_budget() -> None:
    assert _serialized_tool_list_bytes(CLAUDE_COMPUTER_USE_TOOLS) <= (
        CLAUDE_MCP_TOOL_SCHEMA_MAX_BYTES
    )


def test_initialize_and_tools_list_are_local_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, output = _server(monkeypatch)
    try:
        server._handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )
        server._handle_message(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        )
    finally:
        server.close()

    messages = _messages(output)
    assert messages[0]["result"]["serverInfo"]["name"] == "fcc-codex-computer-use"
    assert messages[0]["result"]["protocolVersion"] == "2025-06-18"
    assert messages[1]["result"]["tools"] == list(CLAUDE_COMPUTER_USE_TOOLS)
    assert messages[1]["result"]["ttlMs"] == MCP_TOOL_LIST_TTL_MS
    assert messages[1]["result"]["cacheScope"] == "public"


def test_native_result_returns_content_and_metadata_only_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, output = _server(monkeypatch)

    class FakeExecutor:
        def execute_planned(self, *args: Any, **kwargs: Any) -> HelperExecutionResult:
            return _success_result(str(kwargs["operation"]))

    server._executor = cast(Any, FakeExecutor())
    pending = _PendingCall(
        request_id=7,
        operation="list_apps",
        arguments={},
        cancelled=threading.Event(),
    )
    try:
        server._execute_call(pending)
    finally:
        server.close()

    message = _messages(output)[0]
    assert message["result"]["content"] == [{"type": "text", "text": "ok:list_apps"}]
    assert message["result"]["isError"] is False
    receipt = message["result"]["_meta"]["fccHelperReceipt"]
    assert receipt["helper_id"] == "codex-computer-use"
    assert receipt["local"] is True
    assert receipt["billable"] is False
    assert "arguments" not in receipt
    assert "content" not in receipt


def test_native_result_preserves_structured_image_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bridge must forward native screenshot blocks without flattening them."""
    server, output = _server(monkeypatch)
    native_content = [
        {"type": "text", "text": "Current app state."},
        {"type": "image", "data": "encoded-image", "mimeType": "image/jpeg"},
    ]
    try:
        server._write_native_result(
            "image-1",
            {"content": native_content, "isError": False},
            receipt=_success_result("get_app_state").receipt.as_dict(),
        )
    finally:
        server.close()

    message = _messages(output)[0]
    assert message["id"] == "image-1"
    assert message["result"]["content"] == native_content
    assert message["result"]["isError"] is False


def test_tools_call_queue_returns_one_correlated_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the stdio server's real enqueue/worker/write path."""

    class EventOutput(io.StringIO):
        def __init__(self) -> None:
            super().__init__()
            self.written = threading.Event()

        def write(self, value: str) -> int:
            count = super().write(value)
            self.written.set()
            return count

    monkeypatch.setenv(
        "FCC_CONTROLLER_MODEL_REF",
        "opencode_go/muse-spark-1.2-contributor",
    )
    output = EventOutput()
    server = CodexComputerUseMcpServer(stdin=io.StringIO(), stdout=output)

    class FakeExecutor:
        def execute_planned(self, *args: Any, **kwargs: Any) -> HelperExecutionResult:
            return _success_result(str(kwargs["operation"]))

    server._executor = cast(Any, FakeExecutor())
    try:
        server._handle_message(
            {
                "jsonrpc": "2.0",
                "id": "list-apps-1",
                "method": "tools/call",
                "params": {"name": "list_apps", "arguments": {}},
            }
        )
        assert output.written.wait(timeout=2.0)
    finally:
        server.close()

    messages = _messages(output)
    assert len(messages) == 1
    assert messages[0]["id"] == "list-apps-1"
    assert messages[0]["result"]["content"] == [
        {"type": "text", "text": "ok:list_apps"}
    ]


def test_cancelled_mutation_is_reported_indeterminate_not_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, output = _server(monkeypatch)
    pending = _PendingCall(
        request_id="mutate-1",
        operation="click",
        arguments={"app": "TextEdit", "x": 10, "y": 10},
        cancelled=threading.Event(),
    )

    class CancellingExecutor:
        def execute_planned(self, *args: Any, **kwargs: Any) -> HelperExecutionResult:
            pending.cancelled.set()
            receipt = HelperExecutionReceipt(
                helper_id="codex-computer-use",
                provider_family="computer",
                operation="click",
                status=HelperExecutionStatus.FAILED,
                duration_ms=2,
                attempts=1,
                local=True,
                billable=False,
                failure_owner="codex-computer-use",
            )
            raise HelperExecutionError("transport closed", receipt)

    server._executor = cast(Any, CancellingExecutor())
    try:
        server._execute_call(pending)
    finally:
        server.close()

    result = _messages(output)[0]["result"]
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "indeterminate" in text
    assert "must not be replayed automatically" in text


def test_helper_failure_preserves_actionable_native_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, output = _server(monkeypatch)
    receipt = HelperExecutionReceipt(
        helper_id="codex-computer-use",
        provider_family="computer",
        operation="list_apps",
        status=HelperExecutionStatus.FAILED,
        duration_ms=2,
        attempts=1,
        local=True,
        billable=False,
        failure_owner="codex-computer-use",
    )

    class FailingExecutor:
        def execute_planned(self, *args: Any, **kwargs: Any) -> HelperExecutionResult:
            raise HelperExecutionError(
                "helper execution failed: codex-computer-use",
                receipt,
            ) from CodexComputerUseError(
                "the signed Computer Use app-server launcher is unavailable"
            )

    server._executor = cast(Any, FailingExecutor())
    pending = _PendingCall(
        request_id="native-failure-1",
        operation="list_apps",
        arguments={},
        cancelled=threading.Event(),
    )
    try:
        server._execute_call(pending)
    finally:
        server.close()

    result = _messages(output)[0]["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"] == (
        "Computer Use failed: the signed Computer Use app-server launcher is unavailable"
    )


def test_unknown_tool_is_rejected_before_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, output = _server(monkeypatch)
    try:
        server._handle_message(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "shell", "arguments": {}},
            }
        )
    finally:
        server.close()

    message = _messages(output)[0]
    assert message["error"]["code"] == -32602
    assert "unsupported Computer Use tool" in message["error"]["message"]


def test_policy_counts_computer_use_as_local_not_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _output = _server(monkeypatch)
    try:
        assert server._policy.provider_policy.paid_fallback is False
        assert "openai" in server._policy.provider_policy.forbidden_provider_families
        assert server._policy.allowed_helper_ids == frozenset({"codex-computer-use"})
        assert server._policy.egress_guard.receipt()["counts"] == {}
    finally:
        server.close()


def test_native_app_access_auto_approval_requires_explicit_helper_allowlist() -> None:
    approved = _elicitation_handler(
        approval_mode="auto",
        allowed_helper_ids="local-vision, codex-computer-use",
    )({"message": "Allow Chrome?"})
    assert approved["action"] == "accept"

    declined = _elicitation_handler(
        approval_mode="auto",
        allowed_helper_ids="local-vision",
    )({"message": "Allow Chrome?"})
    assert declined["action"] == "decline"


def test_native_app_access_decline_mode_is_fail_closed() -> None:
    response = _elicitation_handler(
        approval_mode="decline",
        allowed_helper_ids="codex-computer-use",
    )({"message": "Allow Chrome?"})

    assert response == {"action": "decline", "content": None, "_meta": None}
