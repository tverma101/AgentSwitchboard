"""Tests for the signed Codex Computer Use bridge contract."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from free_claude_code.runtime import codex_computer_use as cu


def test_tool_contract_is_stable_and_contains_only_fixed_metadata() -> None:
    first = cu.tool_contract_bytes()
    second = cu.tool_contract_bytes()

    assert first == second
    assert cu.tool_contract_hash() == cu.tool_contract_hash()
    payload = json.loads(first)
    assert [tool["name"] for tool in payload] == list(cu.COMPUTER_USE_METHODS)

    forbidden = (
        b"/Applications/",
        b"/Users/",
        b".codex",
        b"threadId",
        b"TeamIdentifier",
        b"timestamp",
    )
    assert not any(token in first for token in forbidden)


def test_interactions_require_fresh_state_but_reads_do_not() -> None:
    assert cu.interaction_requires_fresh_state("click") is True
    assert cu.interaction_requires_fresh_state("type_text") is True
    assert cu.interaction_requires_fresh_state("get_app_state") is False
    assert cu.interaction_requires_fresh_state("list_apps") is False


def test_broker_environment_isolated_and_drops_api_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("CODEX_API_KEY", "must-not-leak")
    monkeypatch.setenv("LANG", "en_US.UTF-8")

    env = cu._broker_environment(tmp_path, tmp_path / "codex-home")

    assert "OPENAI_API_KEY" not in env
    assert "CODEX_API_KEY" not in env
    assert env["HOME"] == str(tmp_path)
    assert env["CODEX_HOME"] == str(tmp_path / "codex-home")
    assert env["LANG"] == "en_US.UTF-8"


def test_app_server_args_disable_model_paths_and_use_direct_mcp(
    tmp_path: Path,
) -> None:
    paths = cu.CodexComputerUsePaths(
        codex=Path("/signed/codex"),
        app=Path("/signed/Codex Computer Use.app"),
        client=Path("/signed/SkyComputerUseClient"),
    )

    args = cu._app_server_args(paths, tmp_path)
    rendered = "\n".join(args)

    assert 'model_provider="direct_disabled"' in rendered
    assert "features.multi_agent=false" in rendered
    assert "features.memories=false" in rendered
    assert "history.persistence=" in rendered
    assert "mcp_servers.computer-use.command=" in rendered
    assert str(paths.client) in rendered
    assert args[-2:] == ["app-server", "--stdio"]


def test_resolve_rejects_non_macos() -> None:
    with (
        patch.object(cu.sys, "platform", "linux"),
        pytest.raises(cu.CodexComputerUseError, match="only on macOS"),
    ):
        cu.resolve_official_computer_use()


def test_resolve_verifies_codex_and_official_client(tmp_path: Path) -> None:
    home = tmp_path / "home"
    codex = tmp_path / "ChatGPT.app" / "Contents" / "Resources" / "codex"
    client_app = home / ".codex" / "computer-use" / "Codex Computer Use.app"
    client = client_app / cu.CLIENT_RELATIVE_PATH
    codex.parent.mkdir(parents=True)
    client.parent.mkdir(parents=True)
    codex.write_text("", encoding="utf-8")
    client.write_text("", encoding="utf-8")
    os.chmod(codex, 0o755)
    os.chmod(client, 0o755)

    with (
        patch.object(cu.sys, "platform", "darwin"),
        patch.object(cu, "_verify_openai_binary") as verify,
        patch.object(cu.shutil, "which", return_value=None),
    ):
        paths = cu.resolve_official_computer_use(
            home=home,
            codex_override=codex,
        )

    assert paths.codex == codex.resolve()
    assert paths.client == client.resolve()
    assert paths.app == client_app.resolve()
    assert verify.call_count == 2
    verify.assert_any_call(codex.resolve())
    verify.assert_any_call(client.resolve())


def test_call_dispatches_direct_tool_without_model_request() -> None:
    paths = cu.CodexComputerUsePaths(
        codex=Path("/signed/codex"),
        app=Path("/signed/app"),
        client=Path("/signed/client"),
    )
    broker = cu.CodexComputerUseBroker(paths)
    broker._proc = MagicMock()
    broker._proc.poll.return_value = None
    broker._thread_id = "thread-1"

    with patch.object(
        broker,
        "_request",
        return_value={"content": [{"type": "text", "text": "ok"}]},
    ) as request:
        result = broker.call("click", {"app": "TextEdit", "x": 10, "y": 20})

    assert result["content"][0]["text"] == "ok"
    request.assert_called_once_with(
        "mcpServer/tool/call",
        {
            "threadId": "thread-1",
            "server": "computer-use",
            "tool": "click",
            "arguments": {"app": "TextEdit", "x": 10, "y": 20},
        },
        timeout_seconds=cu.DEFAULT_TIMEOUT_SECONDS,
    )


def test_call_rejects_unknown_tool_before_dispatch() -> None:
    paths = cu.CodexComputerUsePaths(
        codex=Path("/signed/codex"),
        app=Path("/signed/app"),
        client=Path("/signed/client"),
    )
    broker = cu.CodexComputerUseBroker(paths)

    with pytest.raises(cu.CodexComputerUseError, match="unsupported"):
        broker.call("shell", {})


def test_model_turn_event_is_fatal() -> None:
    paths = cu.CodexComputerUsePaths(
        codex=Path("/signed/codex"),
        app=Path("/signed/app"),
        client=Path("/signed/client"),
    )
    broker = cu.CodexComputerUseBroker(paths)
    proc = MagicMock()
    proc.stdout = iter(
        [
            json.dumps(
                {
                    "method": "turn/started",
                    "params": {"turn": {"id": "unexpected"}},
                }
            )
            + "\n"
        ]
    )
    broker._proc = proc

    broker._read_stdout()

    assert broker._fatal_error is not None
    assert "model-turn activity" in str(broker._fatal_error)
