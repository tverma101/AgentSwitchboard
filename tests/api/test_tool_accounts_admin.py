from pathlib import Path

from free_claude_code.application.tool_accounts import CodexToolAccountError
from tests.api.support import create_test_app


def _local_client(app):
    from fastapi.testclient import TestClient

    return TestClient(app, client=("127.0.0.1", 50000))


class _FakeToolAccounts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.accounts = [
            {
                "profile": "work",
                "email": "work@example.com",
                "active": True,
                "plan": "pro",
                "usage": {"windows": [{"label": "5h", "remaining_percent": 72.0}]},
            },
            {
                "profile": "personal",
                "email": "personal@example.com",
                "active": False,
                "plan": None,
                "usage": None,
            },
        ]

    def status(self) -> dict:
        return {
            "available": True,
            "state": "ready",
            "storage": "$CODEX_HOME/auth.json",
            "profiles_storage": "$CODEX_HOME/accounts/profiles",
            "accounts": [dict(account) for account in self.accounts],
        }

    def select(self, profile: str) -> dict:
        self.calls.append(("select", profile))
        for account in self.accounts:
            account["active"] = account["profile"] == profile
        return self.status()

    def refresh_usage(self, profile: str) -> dict:
        self.calls.append(("refresh_usage", profile))
        return self.status()

    def refresh_all_usage(self) -> dict:
        self.calls.append(("refresh_all_usage", None))
        result = self.status()
        result["refresh_errors"] = {}
        return result

    def forget(self, profile: str) -> dict:
        self.calls.append(("forget", profile))
        self.accounts = [
            account for account in self.accounts if account["profile"] != profile
        ]
        return self.status()


def test_tool_account_routes_are_loopback_only_uncached_and_credential_free(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    manager = _FakeToolAccounts()
    app = create_test_app(codex_tool_accounts=manager)
    client = _local_client(app)

    status = client.get("/admin/api/tool-accounts")
    selected = client.post("/admin/api/tool-accounts/personal/select", json={})
    usage = client.post("/admin/api/tool-accounts/personal/usage", json={})
    all_usage = client.post("/admin/api/tool-accounts/usage", json={})
    forgotten = client.delete("/admin/api/tool-accounts/personal")

    assert status.status_code == 200
    assert selected.status_code == 200
    assert usage.status_code == 200
    assert all_usage.status_code == 200
    assert forgotten.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert selected.headers["cache-control"] == "no-store"
    assert status.json()["storage"] == "$CODEX_HOME/auth.json"
    assert status.json()["accounts"][0]["email"] == "work@example.com"
    assert "token" not in status.text.lower()
    assert manager.calls == [
        ("select", "personal"),
        ("refresh_usage", "personal"),
        ("refresh_all_usage", None),
        ("forget", "personal"),
    ]

    remote = _local_client(app)
    remote.headers.update({"origin": "https://not-local.example"})
    assert remote.get("/admin/api/tool-accounts").status_code == 403


def test_tool_account_operation_errors_are_safe_conflicts(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))

    class FailingManager(_FakeToolAccounts):
        def select(self, profile: str) -> dict:
            raise CodexToolAccountError("Unknown Codex account profile: missing")

    response = _local_client(
        create_test_app(codex_tool_accounts=FailingManager())
    ).post("/admin/api/tool-accounts/missing/select", json={})

    assert response.status_code == 409
    assert response.json() == {"detail": "Unknown Codex account profile: missing"}
    assert response.headers["cache-control"] == "no-store"
    assert "refresh_token" not in response.text


def test_tool_account_status_is_explicitly_unavailable_without_runtime_manager(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("HOME", str(tmp_path))

    response = _local_client(create_test_app()).get("/admin/api/tool-accounts")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "state": "unavailable",
        "accounts": [],
        "message": "Codex tool account management is unavailable in this runtime.",
    }


def test_admin_account_surface_names_both_independent_stores():
    html = Path("src/free_claude_code/api/admin_static/index.html").read_text(
        encoding="utf-8"
    )
    script = Path("src/free_claude_code/api/admin_static/admin.js").read_text(
        encoding="utf-8"
    )

    assert 'id="view-accounts"' in html
    assert "FCC Provider Account" in html
    assert "Codex Tool Accounts" in html
    assert "~/.fcc/auth/openai.json" in html
    assert "~/.codex/auth.json" in html
    assert 'api("/admin/api/tool-accounts")' in script
    assert "/admin/api/tool-accounts/${encodeURIComponent(profile)}/select" in script
    assert "/admin/api/tool-accounts/${encodeURIComponent(profile)}/usage" in script
    assert "fcc accounts add" in script
    assert "Independent from FCC Provider Account" in script
