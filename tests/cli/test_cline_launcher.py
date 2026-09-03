"""Tests for the FCC-to-Cline local bridge launcher."""

import json
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from free_claude_code.cli.launchers import cline
from free_claude_code.config.settings import Settings


def _settings() -> Settings:
    return Settings.model_construct(
        host="127.0.0.1",
        port=8082,
        model="bai/deepseek-v4-flash",
        anthropic_auth_token="test-fcc-token",
    )


def _provider_file(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "settings" / "providers.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_ensure_local_provider_preserves_existing_cline_lane(tmp_path: Path) -> None:
    path = _provider_file(
        tmp_path,
        {
            "version": 1,
            "lastUsedProvider": "cline",
            "providers": {
                "cline": {"settings": {"provider": "cline", "model": "free"}},
                "anthropic": {"updatedAt": "old", "tokenSource": "oauth"},
            },
        },
    )

    changed = cline._ensure_local_provider(
        path,
        base_url="http://127.0.0.1:8082/v1",
        auth_token="test-fcc-token",
        model="bai/deepseek-v4-flash",
        dry_run=False,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert changed is True
    assert payload["lastUsedProvider"] == "cline"
    assert payload["providers"]["cline"]["settings"]["model"] == "free"
    assert payload["providers"]["anthropic"]["settings"] == {
        "provider": "anthropic",
        "apiKey": "test-fcc-token",
        "model": "bai/deepseek-v4-flash",
        "baseUrl": "http://127.0.0.1:8082/v1",
    }
    assert payload["providers"]["anthropic"]["tokenSource"] == "oauth"


def test_ensure_local_provider_is_idempotent_and_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "settings" / "providers.json"
    kwargs = {
        "base_url": "http://127.0.0.1:8082/v1",
        "auth_token": "test-fcc-token",
        "model": "bai/deepseek-v4-flash",
        "dry_run": False,
    }

    assert cline._ensure_local_provider(path, **kwargs) is True
    assert cline._ensure_local_provider(path, **kwargs) is False
    assert stat.S_IMODE(path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR


def test_ensure_local_provider_dry_run_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / "settings" / "providers.json"

    changed = cline._ensure_local_provider(
        path,
        base_url="http://127.0.0.1:8082/v1",
        auth_token="test-fcc-token",
        model="bai/deepseek-v4-flash",
        dry_run=True,
    )

    assert changed is True
    assert not path.exists()


def test_ensure_local_provider_rejects_malformed_provider_settings(
    tmp_path: Path,
) -> None:
    path = _provider_file(tmp_path, {"providers": []})

    with pytest.raises(cline.ClineBridgeError, match="providers must"):
        cline._ensure_local_provider(
            path,
            base_url="http://127.0.0.1:8082/v1",
            auth_token="test-fcc-token",
            model="bai/deepseek-v4-flash",
            dry_run=False,
        )


def test_cline_data_dir_accepts_cline_pass_through_option(tmp_path: Path) -> None:
    assert cline._cline_data_dir(("--data-dir", str(tmp_path))) == tmp_path
    assert cline._cline_data_dir((f"--data-dir={tmp_path}",)) == tmp_path


def test_launch_configures_and_forwards_cline_arguments(tmp_path: Path) -> None:
    settings = _settings()
    with (
        patch.object(cline, "get_settings", return_value=settings),
        patch.object(cline, "preflight_proxy", return_value=None),
        patch.object(
            cline, "resolve_client_binary", return_value="/usr/local/bin/cline"
        ),
        patch.object(cline, "run_client_process") as run_client,
    ):
        cline.launch(("--fcc-data-dir", str(tmp_path), "prompt text"))

    run_client.assert_called_once()
    call = run_client.call_args.kwargs
    assert call["command"] == [
        "/usr/local/bin/cline",
        "--model",
        "bai/deepseek-v4-flash",
        "--provider",
        "anthropic",
        "prompt text",
    ]
    payload = json.loads(
        (tmp_path / "settings" / "providers.json").read_text(encoding="utf-8")
    )
    assert payload["providers"]["anthropic"]["settings"]["baseUrl"] == (
        "http://127.0.0.1:8082/v1"
    )


def test_launch_preserves_explicit_cline_provider_and_model(tmp_path: Path) -> None:
    settings = _settings()
    with (
        patch.object(cline, "get_settings", return_value=settings),
        patch.object(cline, "preflight_proxy", return_value=None),
        patch.object(cline, "resolve_client_binary", return_value="cline"),
        patch.object(cline, "run_client_process") as run_client,
    ):
        cline.launch(
            (
                "--fcc-data-dir",
                str(tmp_path),
                "-P",
                "anthropic",
                "-m",
                "custom/model",
                "prompt",
            )
        )

    assert run_client.call_args.kwargs["command"] == [
        "cline",
        "-P",
        "anthropic",
        "-m",
        "custom/model",
        "prompt",
    ]


def test_launch_missing_cline_does_not_write_provider_settings(tmp_path: Path) -> None:
    with (
        patch.object(cline, "get_settings", return_value=_settings()),
        patch.object(cline, "preflight_proxy", return_value=None),
        patch.object(
            cline,
            "resolve_client_binary",
            side_effect=SystemExit(127),
        ),
        pytest.raises(SystemExit, match="127"),
    ):
        cline.launch(("--fcc-data-dir", str(tmp_path)))

    assert not (tmp_path / "settings" / "providers.json").exists()


def test_launch_dry_run_does_not_resolve_or_launch(tmp_path: Path, capsys) -> None:
    with (
        patch.object(cline, "get_settings", return_value=_settings()),
        patch.object(cline, "preflight_proxy", return_value=None),
        patch.object(cline, "resolve_client_binary") as resolve_binary,
        patch.object(cline, "run_client_process") as run_client,
    ):
        cline.launch(("--fcc-data-dir", str(tmp_path), "--fcc-dry-run"))

    resolve_binary.assert_not_called()
    run_client.assert_not_called()
    assert "FCC Cline bridge: would update" in capsys.readouterr().out
