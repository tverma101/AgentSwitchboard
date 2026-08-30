from free_claude_code.cli.claude_env import (
    CLAUDE_DISABLE_NONSTREAMING_FALLBACK_ENV,
    build_claude_proxy_env,
)


def _proxy_env(base_env: dict[str, str]) -> dict[str, str]:
    return build_claude_proxy_env(
        proxy_root_url="http://127.0.0.1:8082",
        auth_token="token",
        base_env=base_env,
    )


def test_fcc_proxy_disables_claude_nonstreaming_fallback() -> None:
    env = _proxy_env({})

    assert env[CLAUDE_DISABLE_NONSTREAMING_FALLBACK_ENV] == "1"


def test_inherited_value_cannot_reenable_client_side_replay() -> None:
    env = _proxy_env({CLAUDE_DISABLE_NONSTREAMING_FALLBACK_ENV: "0"})

    assert env[CLAUDE_DISABLE_NONSTREAMING_FALLBACK_ENV] == "1"
