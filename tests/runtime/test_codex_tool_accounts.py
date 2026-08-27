from unittest.mock import patch

from free_claude_code.cli.codex_accounts import CodexAccount
from free_claude_code.runtime.codex_tool_accounts import CodexToolAccountsRuntime


def _account() -> CodexAccount:
    return CodexAccount(
        profile="work",
        account_id="acct-secret-but-not-a-token",
        email="work@example.com",
        active=True,
        plan="pro",
        usage={
            "version": 1,
            "fetched_at": 1_000,
            "approximate": False,
            "plan_type": "pro",
            "windows": [
                {
                    "id": "primary",
                    "label": "5h",
                    "used_percent": 25.0,
                    "remaining_percent": 75.0,
                    "window_seconds": 18_000,
                    "reset_at": 2_000,
                    "refresh_token": "must-not-leak",
                }
            ],
            "refresh_token": "must-not-leak",
        },
    )


def test_codex_account_public_projection_excludes_ids_and_unknown_usage_fields():
    public = _account().public_dict()

    assert public == {
        "profile": "work",
        "email": "work@example.com",
        "active": True,
        "plan": "pro",
        "usage": {
            "version": 1,
            "fetched_at": 1_000,
            "approximate": False,
            "plan_type": "pro",
            "windows": [
                {
                    "id": "primary",
                    "label": "5h",
                    "used_percent": 25.0,
                    "remaining_percent": 75.0,
                    "window_seconds": 18_000,
                    "reset_at": 2_000,
                }
            ],
        },
    }
    assert "acct-secret-but-not-a-token" not in str(public)
    assert "must-not-leak" not in str(public)


def test_codex_tool_runtime_publishes_only_independent_storage_and_safe_accounts():
    runtime = CodexToolAccountsRuntime()
    with patch(
        "free_claude_code.runtime.codex_tool_accounts.codex_accounts.list_accounts",
        return_value=(_account(),),
    ):
        status = runtime.status()

    assert status["storage"] == "$CODEX_HOME/auth.json"
    assert status["profiles_storage"] == "$CODEX_HOME/accounts/profiles"
    assert status["accounts"] == [_account().public_dict()]
    assert "openai.json" not in str(status)
    assert "must-not-leak" not in str(status)
