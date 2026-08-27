"""Admin API contracts for configured custom providers."""

import json
from pathlib import Path

from dotenv import dotenv_values
from fastapi.testclient import TestClient

from free_claude_code.config.settings import Settings
from tests.api.support import create_test_app


def _local_client(app):
    return TestClient(app, client=("127.0.0.1", 50000))


def _set_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)


def _clear_process_config(monkeypatch) -> None:
    for key in (
        "MODEL",
        "NVIDIA_NIM_API_KEY",
        "CUSTOM_PROVIDERS_JSON",
        "ANTHROPIC_AUTH_TOKEN",
        "FCC_ENV_FILE",
    ):
        monkeypatch.delenv(key, raising=False)


def _remote_payload(**overrides: object) -> dict[str, object]:
    return {
        "id": "Acme Gateway",
        "display_name": "Acme Gateway",
        "base_url": "https://api.example.test/v1",
        "api_key": "super-secret",
        "models": ["acme/model"],
        **overrides,
    }


def test_custom_provider_admin_crud_masks_key_and_requires_restart(
    monkeypatch, tmp_path
) -> None:
    _set_home(monkeypatch, tmp_path)
    _clear_process_config(monkeypatch)
    app = create_test_app(Settings(voice_note_enabled=False))
    client = _local_client(app)

    response = client.post(
        "/admin/api/custom-providers",
        json=_remote_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is True
    assert body["restart"]["required"] is True
    assert "super-secret" not in response.text
    assert body["provider"]["provider_id"] == "acme_gateway"
    assert body["provider"]["api_key_configured"] is True

    listed = client.get("/admin/api/custom-providers")
    assert listed.status_code == 200
    provider = listed.json()["providers"][0]
    assert provider["provider_id"] == "acme_gateway"
    assert provider["status"] == "configured"
    assert "api_key" not in provider
    assert "super-secret" not in listed.text

    updated = client.put(
        "/admin/api/custom-providers/acme_gateway",
        json={"display_name": "Acme Updated"},
    )
    assert updated.status_code == 200
    assert "super-secret" not in updated.text
    persisted_raw = dotenv_values(tmp_path / ".fcc" / ".env").get(
        "CUSTOM_PROVIDERS_JSON"
    )
    assert isinstance(persisted_raw, str)
    persisted = json.loads(persisted_raw)
    assert persisted["providers"][0]["api_key"] == "super-secret"
    assert persisted["providers"][0]["display_name"] == "Acme Updated"

    removed = client.delete("/admin/api/custom-providers/acme_gateway")
    assert removed.status_code == 200
    assert client.get("/admin/api/custom-providers").json()["providers"] == []


def test_custom_provider_admin_rejects_arbitrary_fields(monkeypatch, tmp_path) -> None:
    _set_home(monkeypatch, tmp_path)
    _clear_process_config(monkeypatch)

    response = _local_client(create_test_app()).post(
        "/admin/api/custom-providers",
        json=_remote_payload(headers={"X-Anything": "blocked"}),
    )

    assert response.status_code == 422
    assert "super-secret" not in response.text


def test_custom_provider_admin_accepts_loopback_without_key(
    monkeypatch, tmp_path
) -> None:
    _set_home(monkeypatch, tmp_path)
    _clear_process_config(monkeypatch)

    response = _local_client(create_test_app()).post(
        "/admin/api/custom-providers",
        json={
            "id": "local",
            "display_name": "Local",
            "base_url": "http://127.0.0.1:8080/v1",
            "local": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["provider"]["api_key_configured"] is False
