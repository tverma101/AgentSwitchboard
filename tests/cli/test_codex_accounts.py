import base64
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from free_claude_code.cli import codex_accounts


def _jwt(**claims: Any) -> str:
    def part(value: dict[str, Any]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part(claims)}.sig"


def _auth_payload(
    account_id: str,
    email: str,
    *,
    access_token: str | None = None,
    refresh_token: str = "refresh-secret",
) -> dict[str, Any]:
    return {
        "auth_mode": "chatgpt",
        "tokens": {
            "id_token": _jwt(email=email, exp=4_000_000_000),
            "access_token": access_token or _jwt(email=email, exp=4_000_000_000),
            "refresh_token": refresh_token,
            "account_id": account_id,
        },
        "last_refresh": "2026-08-27T12:00:00Z",
    }


def _write_auth(home: Path, payload: dict[str, Any]) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    path = home / "auth.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    if os.name != "nt":
        os.chmod(path, 0o600)
    return path


def test_list_accounts_imports_live_auth_without_exposing_tokens(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".codex"
    _write_auth(home, _auth_payload("acct-1", "me@example.com"))

    accounts = codex_accounts.list_accounts(home=home)

    assert len(accounts) == 1
    account = accounts[0]
    assert account.active is True
    assert account.email == "me@example.com"
    assert account.account_id == "acct-1"
    assert "refresh-secret" not in repr(account)
    saved = codex_accounts.profile_auth_path(account.profile, home)
    assert saved.is_file()
    if os.name != "nt":
        assert saved.stat().st_mode & 0o777 == 0o600


def test_active_account_summary_reads_live_store_without_creating_profiles(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".codex"
    _write_auth(home, _auth_payload("acct-1", "me@example.com"))

    assert codex_accounts.active_account_summary(home=home) == (
        "me@example.com (profile active)"
    )
    assert not codex_accounts.profiles_dir(home).exists()


def test_select_account_snapshots_outgoing_auth_then_restores_target(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".codex"
    _write_auth(home, _auth_payload("acct-a", "a@example.com", refresh_token="a-old"))
    first = codex_accounts.list_accounts(home=home)[0]

    _write_auth(home, _auth_payload("acct-b", "b@example.com", refresh_token="b-live"))
    second = codex_accounts.list_accounts(home=home)[0]
    assert second.account_id == "acct-b"
    assert len(codex_accounts.list_accounts(home=home)) == 2

    _write_auth(
        home,
        _auth_payload("acct-b", "b@example.com", refresh_token="b-rotated"),
    )
    selected = codex_accounts.select_account(first.profile, home=home)

    assert selected.account_id == "acct-a"
    live = json.loads((home / "auth.json").read_text())
    assert live["tokens"]["account_id"] == "acct-a"
    saved_b = json.loads(
        codex_accounts.profile_auth_path(second.profile, home).read_text()
    )
    assert saved_b["tokens"]["refresh_token"] == "b-rotated"


def test_add_account_stashes_live_auth_before_official_login(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    _write_auth(
        home,
        _auth_payload("acct-old", "old@example.com", refresh_token="old-refresh"),
    )
    old_profile = codex_accounts.list_accounts(home=home)[0].profile
    observations: list[bool] = []

    def fake_runner(argv, *, env, check):
        observations.append((home / "auth.json").exists())
        assert argv == ["/usr/local/bin/codex", "login"]
        assert check is False
        assert "OPENAI_API_KEY" not in env
        assert "CODEX_API_KEY" not in env
        _write_auth(
            home,
            _auth_payload("acct-new", "new@example.com", refresh_token="new-refresh"),
        )
        return subprocess.CompletedProcess(argv, 0)

    account = codex_accounts.add_account(
        "new",
        home=home,
        executable="/usr/local/bin/codex",
        runner=fake_runner,
    )

    assert observations == [False]
    assert account.profile == "new"
    assert account.email == "new@example.com"
    assert (
        json.loads((home / "auth.json").read_text())["tokens"]["account_id"]
        == "acct-new"
    )
    old_saved = json.loads(
        codex_accounts.profile_auth_path(old_profile, home).read_text()
    )
    assert old_saved["tokens"]["refresh_token"] == "old-refresh"


def test_add_account_restores_previous_auth_when_login_fails(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    _write_auth(home, _auth_payload("acct-old", "old@example.com"))
    codex_accounts.list_accounts(home=home)

    def fake_runner(argv, *, env, check):
        assert not (home / "auth.json").exists()
        _write_auth(home, _auth_payload("partial", "partial@example.com"))
        return subprocess.CompletedProcess(argv, 9)

    with pytest.raises(codex_accounts.CodexAccountError, match="status 9"):
        codex_accounts.add_account(
            "new",
            home=home,
            executable="codex",
            runner=fake_runner,
        )

    restored = json.loads((home / "auth.json").read_text())
    assert restored["tokens"]["account_id"] == "acct-old"
    assert not codex_accounts.profile_dir("new", home).exists()


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._raw = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def test_refresh_usage_reports_plan_dynamic_windows_and_no_credentials(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".codex"
    _write_auth(
        home,
        _auth_payload(
            "acct-pro",
            "pro@example.com",
            access_token="access-super-secret",
        ),
    )
    profile = codex_accounts.list_accounts(home=home)[0].profile
    seen_headers: dict[str, str] = {}

    def opener(request, *, timeout):
        nonlocal seen_headers
        assert timeout == codex_accounts.USAGE_TIMEOUT_SECONDS
        seen_headers = dict(request.header_items())
        return _Response(
            {
                "plan_type": "pro",
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 31,
                        "limit_window_seconds": 18_000,
                        "reset_at": 2_000_000_000,
                    },
                    "secondary_window": {
                        "used_percent": 58,
                        "limit_window_seconds": 604_800,
                        "reset_at": 2_000_100_000,
                    },
                },
                "additional_rate_limits": [
                    {
                        "limit_name": "codex_other",
                        "rate_limit": {
                            "primary_window": {
                                "used_percent": 88,
                                "limit_window_seconds": 1_800,
                            }
                        },
                    }
                ],
                "credits": {"has_credits": True, "balance": "12.5"},
            }
        )

    usage = codex_accounts.refresh_usage(profile, home=home, opener=opener)

    assert usage["plan_type"] == "pro"
    assert usage["approximate"] is False
    assert usage["windows"][0]["label"] == "5h"
    assert usage["windows"][0]["remaining_percent"] == 69.0
    assert usage["windows"][1]["label"] == "weekly"
    assert usage["windows"][1]["remaining_percent"] == 42.0
    assert usage["additional_limits"][0]["remaining_percent"] == 12.0
    assert usage["credits"]["balance"] == "12.5"
    assert seen_headers["Authorization"] == "Bearer access-super-secret"
    cached = codex_accounts.profile_usage_path(profile, home).read_text()
    assert "access-super-secret" not in cached
    assert "refresh-secret" not in cached


def test_window_labels_follow_backend_duration() -> None:
    assert codex_accounts._window_label(18_000) == "5h"
    assert codex_accounts._window_label(604_800) == "weekly"
    assert codex_accounts._window_label(2_592_000) == "30d"


def test_forget_refuses_active_account(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    _write_auth(home, _auth_payload("acct-1", "me@example.com"))
    profile = codex_accounts.list_accounts(home=home)[0].profile

    with pytest.raises(codex_accounts.CodexAccountError, match="active"):
        codex_accounts.forget_account(profile, home=home)
