"""Tests for FCC's bounded Claude gateway context policy."""

import json

from free_claude_code.cli.claude_env import (
    build_claude_proxy_env,
    claude_settings_env,
    conflicting_settings_env_keys,
    context_cap_tokens,
    effective_context_window,
    model_context_window,
    resolved_model_id,
    settings_env_routing_conflict_message,
)


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


def test_build_claude_proxy_env_always_sets_default_256k() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={},
        model_id="anthropic/opencode_go/deepseek-v4-flash",
    )
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "256000"
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "256000"
    assert "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE" not in env
    assert "CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT" not in env
    assert env["MAX_MCP_OUTPUT_TOKENS"] == "12000"
    assert env["ENABLE_TOOL_SEARCH"] == "true"


def test_build_claude_proxy_env_uses_explicit_override() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={"FCC_CLAUDE_CONTEXT_TOKENS": "192000"},
        model_id="some-1m-model",
    )
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "192000"
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "192000"


def test_build_claude_proxy_env_removes_inherited_compaction_disable() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={
            "CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT": "1",
            "DISABLE_COMPACT": "1",
            "DISABLE_AUTO_COMPACT": "1",
        },
    )

    assert "CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT" not in env
    assert "DISABLE_COMPACT" not in env
    assert "DISABLE_AUTO_COMPACT" not in env


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
