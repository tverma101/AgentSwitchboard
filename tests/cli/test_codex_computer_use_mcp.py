"""Contract tests for Claude's fixed Codex Computer Use MCP surface."""

import io
import json
import threading
from typing import Any

import pytest

from free_claude_code.application.helpers import (
    HelperExecutionError,
    HelperExecutionReceipt,
    HelperExecutionResult,
    HelperExecutionStatus,
)
from free_claude_code.cli.codex_computer_use_mcp import (
    CLAUDE_COMPUTER_USE_TOOLS,
    CodexComputerUseMcpServer,
    _PendingCall,
)
from free_claude_code.runtime.codex_computer_use import COMPUTER_USE_METHODS


def _server(monkeypatch: pytest.MonkeyPatch) -> tuple[CodexComputerUseMcpServer, io.StringIO]:
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
    assert by_name["list_apps"]["annotations"]["readOnlyHint"] is True
    assert by_name["get_app_state"]["annotations"]["readOnlyHint"] is True
    assert by_name["click"]["annotations"]["readOnlyHint"] is False
    assert by_name["type_text"]["annotations"]["idempotentHint"] is False


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


def test_native_result_returns_content_and_metadata_only_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, output = _server(monkeypatch)

    class FakeExecutor:
        def execute_planned(self, *args: Any, **kwargs: Any) -> HelperExecutionResult:
            return _success_result(str(kwargs["operation"]))

    server._executor = FakeExecutor()  # type: ignore[assignment]
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

    server._executor = CancellingExecutor()  # type: ignore[assignment]
    try:
        server._execute_call(pending)
    finally:
        server.close()

    result = _messages(output)[0]["result"]
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "indeterminate" in text
    assert "must not be replayed automatically" in text


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
