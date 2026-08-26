"""Tests for the current managed Codex Computer Use host contract."""

import os
import queue
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from free_claude_code.runtime import codex_computer_use as cu
from free_claude_code.runtime import codex_computer_use_managed as managed


def _paths(tmp_path: Path) -> cu.CodexComputerUsePaths:
    resources = tmp_path / "ChatGPT.app" / "Contents" / "Resources"
    codex = resources / "codex"
    app = tmp_path / "home" / ".codex" / "computer-use" / "Codex Computer Use.app"
    client = app / cu.CLIENT_RELATIVE_PATH
    codex.parent.mkdir(parents=True, exist_ok=True)
    client.parent.mkdir(parents=True, exist_ok=True)
    codex.write_text("", encoding="utf-8")
    client.write_text("", encoding="utf-8")
    os.chmod(codex, 0o755)
    os.chmod(client, 0o755)
    return cu.CodexComputerUsePaths(codex=codex, app=app, client=client)


def test_managed_environment_drops_api_keys_and_keeps_codex_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "never-forward")
    monkeypatch.setenv("CODEX_API_KEY", "never-forward")
    home = tmp_path / "home"
    codex_home = home / ".codex"
    home.mkdir()
    codex_home.mkdir()

    env = managed.managed_broker_environment(
        temp_root=tmp_path / "tmp",
        user_home=home,
        codex_home=codex_home,
    )

    assert env["HOME"] == str(home.resolve())
    assert env["CODEX_HOME"] == str(codex_home.resolve())
    assert "OPENAI_API_KEY" not in env
    assert "CODEX_API_KEY" not in env


def test_managed_args_enable_current_host_features_and_disable_model() -> None:
    args = managed.managed_app_server_args()
    rendered = "\n".join(args)

    assert 'model_provider="computer_use_disabled"' in rendered
    assert "features.multi_agent=false" in rendered
    assert "features.memories=false" in rendered
    assert "history.persistence=" in rendered
    assert args.count("--enable") == len(managed.FEATURE_FLAGS)
    for feature in managed.FEATURE_FLAGS:
        assert feature in args


def test_managed_config_prefers_bundled_launcher(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    plugin = paths.codex.parent / managed.PLUGIN_RELATIVE_PATH
    launcher = plugin / managed.LAUNCHER_RELATIVE_PATH
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    os.chmod(launcher, 0o755)

    config = managed.managed_mcp_config(paths)

    assert config["command"] == str(launcher.resolve())
    assert config["args"] == ["mcp"]
    assert config["cwd"] == str(plugin.resolve())
    assert config["env_vars"] == ["CODEX_HOME"]
    assert config["enabled"] is True


def test_managed_config_falls_back_to_verified_direct_client(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    config = managed.managed_mcp_config(paths)

    assert config["command"] == str(paths.client)
    assert config["args"] == ["mcp"]
    assert config["enabled"] is True


def test_thread_start_is_ephemeral_on_request_and_only_registers_computer_use(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    params = managed.managed_thread_start_params(paths, tmp_path / "work")

    assert params["ephemeral"] is True
    assert params["approvalPolicy"] == "on-request"
    assert params["sandbox"] == "workspace-write"
    assert set(params["config"]["mcp_servers"]) == {"computer-use"}
    assert params["config"]["features"] == {
        "computer_use": True,
        "plugins": True,
        "tool_call_mcp_elicitation": True,
    }


def test_readiness_requires_all_ten_native_tools(tmp_path: Path) -> None:
    broker = managed.ManagedCodexComputerUseBroker(
        _paths(tmp_path),
        readiness_timeout_seconds=0.2,
    )
    broker._thread_id = "thread-1"
    tool_map = {name: {} for name in cu.COMPUTER_USE_METHODS}

    with patch.object(
        broker,
        "_list_mcp_status",
        return_value=[
            {
                "name": "computer-use",
                "authStatus": "notApplicable",
                "tools": tool_map,
            }
        ],
    ):
        broker._wait_until_ready()

    assert broker.native_tool_names == frozenset(cu.COMPUTER_USE_METHODS)
    assert broker.native_auth_status == "notApplicable"


def test_readiness_fails_closed_when_native_tool_is_missing(tmp_path: Path) -> None:
    broker = managed.ManagedCodexComputerUseBroker(
        _paths(tmp_path),
        readiness_timeout_seconds=0.01,
    )
    broker._thread_id = "thread-1"
    with (
        patch.object(
            broker,
            "_list_mcp_status",
            return_value=[
                {
                    "name": "computer-use",
                    "tools": {"list_apps": {}, "get_app_state": {}},
                }
            ],
        ),
        patch.object(managed.time, "sleep", return_value=None),
        pytest.raises(managed.CodexComputerUseReadinessError, match="missing tools"),
    ):
        broker._wait_until_ready()


def test_status_paginates_until_next_cursor_is_absent(tmp_path: Path) -> None:
    broker = managed.ManagedCodexComputerUseBroker(_paths(tmp_path))
    broker._thread_id = "thread-1"
    with patch.object(
        broker,
        "_request_managed",
        side_effect=[
            {
                "data": [{"name": "other", "tools": {}}],
                "nextCursor": "next",
            },
            {
                "data": [{"name": "computer-use", "tools": {}}],
                "nextCursor": None,
            },
        ],
    ) as request:
        rows = broker._list_mcp_status(managed.time.monotonic() + 1)

    assert [row["name"] for row in rows] == ["other", "computer-use"]
    assert request.call_count == 2
    assert request.call_args_list[1].args[1]["cursor"] == "next"


def test_default_elicitation_fails_closed_with_cancel(tmp_path: Path) -> None:
    broker = managed.ManagedCodexComputerUseBroker(_paths(tmp_path))
    broker._proc = MagicMock()
    broker._proc.poll.return_value = None

    with patch.object(broker, "_write") as write:
        broker._handle_server_request(
            {
                "id": 7,
                "method": "mcpServer/elicitation/request",
                "params": {"message": "Allow Finder?"},
            }
        )

    write.assert_called_once_with(
        {
            "id": 7,
            "result": {"action": "cancel", "content": None, "_meta": None},
        }
    )
    assert broker.elicitation_count == 1


def test_explicit_elicitation_handler_can_accept(tmp_path: Path) -> None:
    broker = managed.ManagedCodexComputerUseBroker(
        _paths(tmp_path),
        elicitation_handler=lambda params: {
            "action": "accept",
            "content": {},
            "_meta": None,
        },
    )
    broker._proc = MagicMock()
    broker._proc.poll.return_value = None

    with patch.object(broker, "_write") as write:
        broker._handle_server_request(
            {
                "id": "approval-1",
                "method": "mcpServer/elicitation/request",
                "params": {"message": "Allow TextEdit?"},
            }
        )

    assert write.call_args.args[0]["result"]["action"] == "accept"
    assert broker.elicitation_count == 1


def test_invalid_elicitation_handler_cancels_and_marks_session_fatal(
    tmp_path: Path,
) -> None:
    broker = managed.ManagedCodexComputerUseBroker(
        _paths(tmp_path),
        elicitation_handler=lambda params: {"action": "yes"},
    )
    broker._proc = MagicMock()
    broker._proc.poll.return_value = None

    with patch.object(broker, "_write") as write:
        broker._handle_server_request(
            {
                "id": 2,
                "method": "mcpServer/elicitation/request",
                "params": {},
            }
        )

    assert write.call_args.args[0]["result"]["action"] == "cancel"
    assert isinstance(
        broker._fatal_error,
        managed.CodexComputerUseElicitationError,
    )


def test_unknown_server_request_gets_method_not_found(tmp_path: Path) -> None:
    broker = managed.ManagedCodexComputerUseBroker(_paths(tmp_path))
    with patch.object(broker, "_write") as write:
        broker._handle_server_request(
            {"id": 3, "method": "something/else", "params": {}}
        )

    response = write.call_args.args[0]
    assert response["id"] == 3
    assert response["error"]["code"] == -32601


def test_mutating_transport_timeout_is_indeterminate(tmp_path: Path) -> None:
    broker = managed.ManagedCodexComputerUseBroker(_paths(tmp_path))
    proc = MagicMock()
    proc.poll.return_value = None
    proc.stdin = MagicMock()
    broker._proc = proc
    broker._thread_id = "thread-1"
    broker._messages = queue.Queue()

    with (
        patch.object(broker, "close") as close,
        pytest.raises(
            managed.CodexComputerUseIndeterminateError,
            match="timed out after dispatch",
        ),
    ):
        broker.call(
            "click",
            {"app": "TextEdit", "x": 10, "y": 10},
            timeout_seconds=0.001,
        )

    close.assert_called_once()


def test_read_only_transport_timeout_is_not_indeterminate(tmp_path: Path) -> None:
    broker = managed.ManagedCodexComputerUseBroker(_paths(tmp_path))
    proc = MagicMock()
    proc.poll.return_value = None
    proc.stdin = MagicMock()
    broker._proc = proc
    broker._thread_id = "thread-1"
    broker._messages = queue.Queue()

    with (
        patch.object(broker, "close"),
        pytest.raises(cu.CodexComputerUseError) as captured,
    ):
        broker.call("list_apps", {}, timeout_seconds=0.001)

    assert not isinstance(
        captured.value,
        managed.CodexComputerUseIndeterminateError,
    )
