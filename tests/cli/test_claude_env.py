"""Tests for per-model context-window overrides in the Claude proxy env."""

import json

from free_claude_code.cli.claude_env import (
    build_claude_proxy_env,
    model_context_window,
    resolved_model_id,
)


def test_model_context_window_matches_flash_model_ids() -> None:
    for model_id in [
        "anthropic/opencode/deepseek-v4-flash-free",
        "anthropic/opencode_go/deepseek-v4-flash",
        "anthropic/opencode/deepseek-v4-flash",
        "DeepSeek-V4-Flash",
    ]:
        assert model_context_window(model_id) == 400000


def test_model_context_window_returns_none_for_other_models() -> None:
    for model_id in [
        "sonnet",
        "fable",
        "nvidia_nim/z-ai/glm-5.2",
        "anthropic/opencode_go/deepseek-v4-pro",
        "anthropic/opencode/deepseek-v3",
        "",
        None,
    ]:
        assert model_context_window(model_id) is None


def test_build_claude_proxy_env_raises_window_for_flash() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={},
        model_id="anthropic/opencode/deepseek-v4-flash-free",
    )
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "400000"
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "400000"


def test_build_claude_proxy_env_keeps_default_for_other_model() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={},
        model_id="sonnet",
    )
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "190000"
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in env


def test_build_claude_proxy_env_defaults_when_no_model_resolved() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={},
    )
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "190000"
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in env


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
