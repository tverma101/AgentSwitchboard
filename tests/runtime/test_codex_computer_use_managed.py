"""Tests for the current managed Codex Computer Use host contract."""

import os
import queue
from itertools import pairwise
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
    assert "features.remote_control=false" not in rendered
    assert "history.persistence=" in rendered
    assert args.count("--enable") == len(managed.FEATURE_FLAGS)
    assert all(not (left == right == "-c") for left, right in pairwise(args))
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


def test_managed_config_rejects_retired_direct_client_fallback(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    with pytest.raises(
        managed.CodexComputerUseError,
        match="refusing the retired direct SkyComputerUseClient path",
    ):
        managed.managed_mcp_config(paths)


def test_install_claude_launcher_copies_official_script_into_profile_namespace(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    plugin = paths.codex.parent / managed.PLUGIN_RELATIVE_PATH
    source = plugin / managed.LAUNCHER_RELATIVE_PATH
    source.parent.mkdir(parents=True)
    source_bytes = b'#!/bin/sh\nset -eu\nexec native-client "$@"\n'
    source.write_bytes(source_bytes)
    os.chmod(source, 0o755)

    destination = managed.install_claude_native_launcher(
        paths,
        claude_config_dir=tmp_path / "claude-profile",
    )

    assert destination == (
        tmp_path / "claude-profile" / managed.CLAUDE_LAUNCHER_RELATIVE_PATH
    )
    assert destination.read_bytes() == source_bytes
    assert destination.stat().st_mode & 0o111
    assert (destination.parent.parent / ".fcc-managed").read_text(
        encoding="utf-8"
    ) == managed.CLAUDE_LAUNCHER_MARKER


def test_install_claude_launcher_refreshes_only_our_copy(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    plugin = paths.codex.parent / managed.PLUGIN_RELATIVE_PATH
    source = plugin / managed.LAUNCHER_RELATIVE_PATH
    source.parent.mkdir(parents=True)
    source.write_bytes(b"#!/bin/sh\nfirst\n")
    os.chmod(source, 0o755)
    claude_config_dir = tmp_path / "claude-profile"

    destination = managed.install_claude_native_launcher(
        paths,
        claude_config_dir=claude_config_dir,
    )
    source.write_bytes(b"#!/bin/sh\nupdated\n")

    refreshed = managed.install_claude_native_launcher(
        paths,
        claude_config_dir=claude_config_dir,
    )

    assert refreshed == destination
    assert destination.read_bytes() == b"#!/bin/sh\nupdated\n"


def test_install_claude_launcher_refuses_user_owned_destination(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    plugin = paths.codex.parent / managed.PLUGIN_RELATIVE_PATH
    source = plugin / managed.LAUNCHER_RELATIVE_PATH
    source.parent.mkdir(parents=True)
    source.write_bytes(b"#!/bin/sh\n")
    os.chmod(source, 0o755)
    claude_config_dir = tmp_path / "claude-profile"
    destination = claude_config_dir / managed.CLAUDE_LAUNCHER_RELATIVE_PATH
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"user launcher\n")

    with pytest.raises(managed.CodexComputerUseError, match="non-FCC file"):
        managed.install_claude_native_launcher(
            paths,
            claude_config_dir=claude_config_dir,
        )

    assert destination.read_bytes() == b"user launcher\n"


def test_thread_start_is_ephemeral_on_request_and_only_registers_computer_use(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    plugin = paths.codex.parent / managed.PLUGIN_RELATIVE_PATH
    launcher = plugin / managed.LAUNCHER_RELATIVE_PATH
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    os.chmod(launcher, 0o755)
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
        patch.object(broker, "_refresh_before_mutation") as refresh,
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

    refresh.assert_called_once_with(
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


def test_read_only_remote_connection_is_restarted_once(tmp_path: Path) -> None:
    broker = managed.ManagedCodexComputerUseBroker(_paths(tmp_path))
    proc = MagicMock()
    proc.poll.return_value = None
    broker._proc = proc
    broker._thread_id = "thread-1"
    disconnected = {
        "content": [{"type": "text", "text": "remoteConnection"}],
        "isError": True,
    }
    recovered = {"content": [{"type": "text", "text": "apps"}], "isError": False}

    with (
        patch.object(
            broker, "_request_managed", side_effect=[disconnected, recovered]
        ) as request,
        patch.object(broker, "close") as close,
        patch.object(broker, "start") as start,
    ):
        result = broker.call("list_apps", {})

    assert result == recovered
    assert request.call_count == 2
    close.assert_called_once_with()
    start.assert_called_once_with()


def test_read_only_transport_error_is_restarted_once(tmp_path: Path) -> None:
    broker = managed.ManagedCodexComputerUseBroker(_paths(tmp_path))
    proc = MagicMock()
    proc.poll.return_value = None
    broker._proc = proc
    broker._thread_id = "thread-1"
    recovered = {"content": [{"type": "text", "text": "apps"}], "isError": False}

    with (
        patch.object(
            broker,
            "_request_managed",
            side_effect=[
                cu.CodexComputerUseError("Codex app-server exited during list_apps"),
                recovered,
            ],
        ) as request,
        patch.object(broker, "close") as close,
        patch.object(broker, "start") as start,
    ):
        result = broker.call("list_apps", {})

    assert result == recovered
    assert request.call_count == 2
    close.assert_called_once_with()
    start.assert_called_once_with()


def test_mutating_call_refreshes_state_and_normalizes_element_alias(
    tmp_path: Path,
) -> None:
    broker = managed.ManagedCodexComputerUseBroker(_paths(tmp_path))
    proc = MagicMock()
    proc.poll.return_value = None
    broker._proc = proc
    broker._thread_id = "thread-1"
    state = {"content": [{"type": "text", "text": "state"}], "isError": False}
    result = {"content": [{"type": "text", "text": "clicked"}], "isError": False}

    with patch.object(
        broker, "_request_managed", side_effect=[state, result]
    ) as request:
        assert (
            broker.call(
                "click",
                {"app": "Calculator", "element": 9},
            )
            == result
        )

    assert request.call_count == 2
    assert request.call_args_list[0].args[0] == "mcpServer/tool/call"
    assert request.call_args_list[0].args[1]["tool"] == "get_app_state"
    assert request.call_args_list[0].args[1]["arguments"] == {"app": "Calculator"}
    assert request.call_args_list[1].args[1]["tool"] == "click"
    assert request.call_args_list[1].args[1]["arguments"] == {
        "app": "Calculator",
        "element_index": "9",
    }


def test_mutating_remote_connection_is_explained_without_replay(
    tmp_path: Path,
) -> None:
    broker = managed.ManagedCodexComputerUseBroker(_paths(tmp_path))
    proc = MagicMock()
    proc.poll.return_value = None
    broker._proc = proc
    broker._thread_id = "thread-1"
    result_with_image = {
        "content": [
            {"type": "text", "text": "remoteConnection"},
            {"type": "image", "data": "encoded", "mimeType": "image/jpeg"},
        ],
        "isError": True,
        "_meta": {"native": "preserved"},
    }

    with (
        patch.object(broker, "_refresh_before_mutation") as refresh,
        patch.object(
            broker, "_request_managed", return_value=result_with_image
        ) as request,
        patch.object(broker, "close") as close,
        patch.object(broker, "start") as start,
    ):
        result = broker.call(
            "click",
            {"app": "Calculator", "element_index": "9"},
        )

    assert request.call_count == 1
    refresh.assert_called_once_with(
        "click",
        {"app": "Calculator", "element_index": "9"},
        timeout_seconds=broker.timeout_seconds,
    )
    close.assert_not_called()
    start.assert_not_called()
    assert result["isError"] is True
    assert "outcome is unknown" in result["content"][0]["text"]
    assert "did not replay" in result["content"][0]["text"]
    assert result["content"][1] == {
        "type": "image",
        "data": "encoded",
        "mimeType": "image/jpeg",
    }
    assert result["_meta"] == {"native": "preserved"}
