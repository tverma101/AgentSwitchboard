"""Tests for FCC's bounded Claude gateway context policy."""

import json

import pytest

from free_claude_code.cli.claude_env import (
    CLAUDE_EFFORT_DEFAULT,
    CLAUDE_EFFORT_LEVEL_ENV,
    build_claude_proxy_env,
    claude_effort_environment,
    claude_settings_env,
    conflicting_settings_env_keys,
    context_cap_tokens,
    effective_context_window,
    model_context_window,
    resolved_model_id,
    settings_env_routing_conflict_message,
)


@pytest.fixture(autouse=True)
def _standard_server_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FCC_SERVER_MODE", raising=False)


def test_default_context_cap_is_256k() -> None:
    assert context_cap_tokens({}) == 256_000
    assert effective_context_window("some-1m-model", {}) == 256_000


def test_explicit_context_override_is_bounded() -> None:
    assert context_cap_tokens({"FCC_CLAUDE_CONTEXT_TOKENS": "128000"}) == 128_000
    assert context_cap_tokens({"FCC_CLAUDE_CONTEXT_TOKENS": "1000000"}) == 1_000_000
    assert context_cap_tokens({"FCC_CLAUDE_CONTEXT_TOKENS": "31999"}) == 256_000
    assert context_cap_tokens({"FCC_CLAUDE_CONTEXT_TOKENS": "1000001"}) == 256_000
    assert context_cap_tokens({"FCC_CLAUDE_CONTEXT_TOKENS": "garbage"}) == 256_000


def test_model_context_window_has_no_large_window_auto_raise() -> None:
    for model_id in [
        "anthropic/opencode/deepseek-v4-flash-free",
        "anthropic/opencode_go/deepseek-v4-flash",
        "DeepSeek-V4-Flash",
        "some-1m-model",
        "",
        None,
    ]:
        assert model_context_window(model_id) is None


def test_claude_effort_environment_defaults_to_remote_xhigh() -> None:
    args = ("--model", "anthropic/opencode_go/deepseek-v4-flash")

    assert claude_effort_environment(args, {}) == {
        CLAUDE_EFFORT_LEVEL_ENV: CLAUDE_EFFORT_DEFAULT,
    }


def test_claude_effort_environment_preserves_explicit_separate_effort() -> None:
    args = ("--effort", "high")

    assert claude_effort_environment(args, {}) == {}


def test_claude_effort_environment_preserves_explicit_equals_effort() -> None:
    args = ("--effort=xhigh",)

    assert claude_effort_environment(args, {}) == {}


def test_claude_effort_environment_preserves_explicit_environment_effort() -> None:
    args = ("--model", "sonnet")

    assert claude_effort_environment(args, {CLAUDE_EFFORT_LEVEL_ENV: "high"}) == {
        CLAUDE_EFFORT_LEVEL_ENV: "high"
    }


def test_claude_effort_environment_treats_blank_environment_effort_as_unset() -> None:
    args = ("--model", "sonnet")

    assert claude_effort_environment(args, {CLAUDE_EFFORT_LEVEL_ENV: "  "}) == {
        CLAUDE_EFFORT_LEVEL_ENV: CLAUDE_EFFORT_DEFAULT
    }


def test_claude_effort_environment_does_not_mutate_input() -> None:
    args = ["--model", "sonnet"]
    base_env = {"EDITOR": "vim"}

    result = claude_effort_environment(args, base_env)

    assert args == ["--model", "sonnet"]
    assert base_env == {"EDITOR": "vim"}
    assert result == {"EDITOR": "vim", CLAUDE_EFFORT_LEVEL_ENV: CLAUDE_EFFORT_DEFAULT}
    assert result is not base_env


def test_build_claude_proxy_env_does_not_inject_other_client_policy() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={},
        model_id="anthropic/opencode_go/deepseek-v4-flash",
    )
    assert "CLAUDE_CODE_AUTO_COMPACT_WINDOW" not in env
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in env
    assert "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE" not in env
    assert "CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT" not in env
    assert "MAX_MCP_OUTPUT_TOKENS" not in env
    assert "ENABLE_TOOL_SEARCH" not in env


def test_build_claude_proxy_env_applies_exact_model_context_mapping() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={},
        model_id="provider/model",
        context_windows={"provider/model": 500_000},
    )

    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "500000"
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "500000"


def test_virtual_model_context_suffix_precedes_saved_mapping() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={},
        model_id="provider/model[128k]",
        context_windows={"provider/model": 500_000},
    )

    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "128000"
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "128000"


def test_build_claude_proxy_env_restores_256k_context_only_in_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FCC_SERVER_MODE", "sandbox")

    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8083",
        auth_token="token",
        base_env={},
        model_id="anthropic/opencode_go/deepseek-v4-flash",
    )

    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "256000"
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "256000"
    assert "MAX_MCP_OUTPUT_TOKENS" not in env
    assert "ENABLE_TOOL_SEARCH" not in env


def test_sandbox_context_window_uses_legacy_fcc_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FCC_SERVER_MODE", "sandbox")

    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8083",
        auth_token="token",
        base_env={"FCC_CLAUDE_CONTEXT_TOKENS": "192000"},
    )

    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "192000"
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "192000"


def test_build_claude_proxy_env_preserves_explicit_context_policy() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={
            "FCC_CLAUDE_CONTEXT_TOKENS": "192000",
            "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "190000",
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "190000",
        },
        model_id="some-1m-model",
    )
    assert env["FCC_CLAUDE_CONTEXT_TOKENS"] == "192000"
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "190000"
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "190000"


def test_build_claude_proxy_env_preserves_inherited_compaction_controls() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={
            "CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT": "1",
            "DISABLE_COMPACT": "1",
            "DISABLE_AUTO_COMPACT": "1",
        },
    )

    assert env["CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"] == "1"
    assert env["DISABLE_COMPACT"] == "1"
    assert env["DISABLE_AUTO_COMPACT"] == "1"


def test_build_claude_proxy_env_preserves_explicit_compaction_threshold() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "85"},
    )

    assert env["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] == "85"


def test_build_claude_proxy_env_preserves_explicit_mcp_output_cap() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={"MAX_MCP_OUTPUT_TOKENS": "25000"},
    )

    assert env["MAX_MCP_OUTPUT_TOKENS"] == "25000"


def test_build_claude_proxy_env_preserves_explicit_tool_search_setting() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={"ENABLE_TOOL_SEARCH": "auto:5"},
    )

    assert env["ENABLE_TOOL_SEARCH"] == "auto:5"


def test_build_claude_proxy_env_propagates_absolute_process_wrapper() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={},
        model_id="muse-spark-1.2-contributor",
        process_wrapper_path="/private/tmp/fcc-wrapper",
    )

    assert env["CLAUDE_CODE_PROCESS_WRAPPER"] == "/private/tmp/fcc-wrapper"


def test_resolved_model_id_prefers_argv_over_env(tmp_path) -> None:
    base_env = _settings_env(
        tmp_path, saved="anthropic/opencode/deepseek-v4-flash-free"
    )
    base_env["CLAUDE_MODEL"] = "sonnet"
    assert (
        resolved_model_id(["--model", "nvidia_nim/z-ai/glm-5.2"], base_env)
        == "nvidia_nim/z-ai/glm-5.2"
    )
    assert resolved_model_id(["--model=haiku"], base_env) == "haiku"
    assert resolved_model_id(["-m", "opus"], base_env) == "opus"


def test_resolved_model_id_prefers_env_over_saved_settings(tmp_path) -> None:
    base_env = _settings_env(
        tmp_path, saved="anthropic/opencode/deepseek-v4-flash-free"
    )
    base_env["CLAUDE_MODEL"] = "sonnet"
    assert resolved_model_id([], base_env) == "sonnet"


def test_resolved_model_id_falls_back_to_saved_settings(tmp_path) -> None:
    base_env = _settings_env(
        tmp_path, saved="anthropic/opencode/deepseek-v4-flash-free"
    )
    assert (
        resolved_model_id([], base_env) == "anthropic/opencode/deepseek-v4-flash-free"
    )


def test_resolved_model_id_ignores_missing_settings(tmp_path) -> None:
    base_env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "missing")}
    assert resolved_model_id([], base_env) is None


def _settings_env(tmp_path, *, saved: str) -> dict[str, str]:
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(json.dumps({"model": saved}))
    return {"CLAUDE_CONFIG_DIR": str(settings_dir)}


def test_claude_settings_env_returns_empty_without_settings(tmp_path) -> None:
    base_env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "missing")}
    assert claude_settings_env(base_env) == {}


def test_claude_settings_env_reads_env_block(tmp_path) -> None:
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "model": "anthropic/opencode/deepseek-v4-flash-free",
                "env": {
                    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
                    "CLAUDE_MODEL": "sonnet",
                },
            }
        )
    )
    base_env = {"CLAUDE_CONFIG_DIR": str(settings_dir)}
    assert claude_settings_env(base_env) == {
        "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
        "CLAUDE_MODEL": "sonnet",
    }


def test_conflicting_settings_env_keys_detects_routing_overrides(tmp_path) -> None:
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
                    "ANTHROPIC_AUTH_TOKEN": "leaked-token",
                    "ANTHROPIC_API_KEY": "sk-ant-leaked",
                    "CLAUDE_MODEL": "sonnet",
                    "EDITOR": "code",
                },
            }
        )
    )
    base_env = {"CLAUDE_CONFIG_DIR": str(settings_dir)}
    conflicts = conflicting_settings_env_keys(base_env)
    assert conflicts == (
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
    )
    # Non-routing keys are never conflicts.
    assert "CLAUDE_MODEL" not in conflicts
    assert "EDITOR" not in conflicts


def test_conflicting_settings_env_keys_ignores_invalid_settings(tmp_path) -> None:
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text("not json{")
    base_env = {"CLAUDE_CONFIG_DIR": str(settings_dir)}
    assert conflicting_settings_env_keys(base_env) == ()

    (settings_dir / "settings.json").write_text(json.dumps({"env": []}))
    assert conflicting_settings_env_keys(base_env) == ()


def test_conflicting_settings_env_keys_ignores_missing_settings(tmp_path) -> None:
    base_env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "missing")}
    assert conflicting_settings_env_keys(base_env) == ()


def test_conflicting_settings_env_keys_covers_project_and_local_sources(
    tmp_path,
) -> None:
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://project.invalid"}})
    )
    (settings_dir / "settings.local.json").write_text(
        json.dumps({"env": {"ANTHROPIC_AUTH_TOKEN": "secret"}})
    )

    conflicts = conflicting_settings_env_keys(
        {"CLAUDE_CONFIG_DIR": str(tmp_path / "missing-user")},
        cwd=tmp_path,
    )

    assert conflicts == ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")


def test_setting_sources_filter_does_not_inspect_disabled_project_layers(
    tmp_path,
) -> None:
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://project.invalid"}})
    )

    assert (
        conflicting_settings_env_keys(
            {"CLAUDE_CONFIG_DIR": str(tmp_path / "missing-user")},
            cwd=tmp_path,
            argv=["--setting-sources", "user"],
        )
        == ()
    )


def test_explicit_settings_overlay_is_checked_without_leaking_values(tmp_path) -> None:
    overlay = json.dumps(
        {
            "env": {
                "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
                "ANTHROPIC_AUTH_TOKEN": "do-not-print",
            }
        }
    )
    message = settings_env_routing_conflict_message(
        {"CLAUDE_CONFIG_DIR": str(tmp_path / "missing-user")},
        cwd=tmp_path,
        argv=["--settings", overlay],
    )

    assert message is not None
    assert "ANTHROPIC_BASE_URL" in message
    assert "ANTHROPIC_AUTH_TOKEN" in message
    assert "do-not-print" not in message
    assert "--settings overlay" in message
