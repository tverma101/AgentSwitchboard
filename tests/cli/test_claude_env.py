"""Tests for FCC's bounded Claude gateway context policy."""

import json

from free_claude_code.cli.claude_env import (
    build_claude_proxy_env,
    context_cap_tokens,
    effective_context_window,
    model_context_window,
    resolved_model_id,
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
    assert env["CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"] == "1"


def test_build_claude_proxy_env_uses_explicit_override() -> None:
    env = build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env={"FCC_CLAUDE_CONTEXT_TOKENS": "192000"},
        model_id="some-1m-model",
    )
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "192000"
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "192000"


def test_resolved_model_id_prefers_argv_over_env(tmp_path) -> None:
    base_env = _settings_env(tmp_path, saved="anthropic/opencode/deepseek-v4-flash-free")
    base_env["CLAUDE_MODEL"] = "sonnet"
    assert (
        resolved_model_id(["--model", "nvidia_nim/z-ai/glm-5.2"], base_env)
        == "nvidia_nim/z-ai/glm-5.2"
    )
    assert resolved_model_id(["--model=haiku"], base_env) == "haiku"
    assert resolved_model_id(["-m", "opus"], base_env) == "opus"


def test_resolved_model_id_prefers_env_over_saved_settings(tmp_path) -> None:
    base_env = _settings_env(tmp_path, saved="anthropic/opencode/deepseek-v4-flash-free")
    base_env["CLAUDE_MODEL"] = "sonnet"
    assert resolved_model_id([], base_env) == "sonnet"


def test_resolved_model_id_falls_back_to_saved_settings(tmp_path) -> None:
    base_env = _settings_env(tmp_path, saved="anthropic/opencode/deepseek-v4-flash-free")
    assert resolved_model_id([], base_env) == "anthropic/opencode/deepseek-v4-flash-free"


def test_resolved_model_id_ignores_missing_settings(tmp_path) -> None:
    base_env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "missing")}
    assert resolved_model_id([], base_env) is None


def _settings_env(tmp_path, *, saved: str) -> dict[str, str]:
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(json.dumps({"model": saved}))
    return {"CLAUDE_CONFIG_DIR": str(settings_dir)}
