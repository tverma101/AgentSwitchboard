import json
from unittest.mock import patch

import pytest

from free_claude_code.cli.launchers.common import (
    is_proxy_version_mismatch,
    preflight_proxy,
)
from free_claude_code.config.settings import Settings


class _HealthResponse:
    def __init__(self, payload: dict[str, object], status: int = 200) -> None:
        self._payload = payload
        self._status = status

    def __enter__(self) -> _HealthResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def getcode(self) -> int:
        return self._status

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_preflight_accepts_matching_running_fcc_version() -> None:
    response = _HealthResponse({"status": "healthy", "version": "4.30.26"})
    with (
        patch(
            "free_claude_code.cli.launchers.common.open_local_request",
            return_value=response,
        ),
        patch(
            "free_claude_code.cli.launchers.common.package_version",
            return_value="4.30.26",
        ),
    ):
        assert preflight_proxy("http://127.0.0.1:8082") is None


def test_preflight_rejects_stale_running_fcc_version() -> None:
    response = _HealthResponse({"status": "healthy", "version": "4.30.25"})
    with (
        patch(
            "free_claude_code.cli.launchers.common.open_local_request",
            return_value=response,
        ),
        patch(
            "free_claude_code.cli.launchers.common.package_version",
            return_value="4.30.26",
        ),
    ):
        error = preflight_proxy("http://127.0.0.1:8082")

    assert error == "FCC version mismatch: running 4.30.25, installed 4.30.26"
    assert is_proxy_version_mismatch(error)


def test_preflight_rejects_legacy_health_without_version() -> None:
    response = _HealthResponse({"status": "healthy"})
    with (
        patch(
            "free_claude_code.cli.launchers.common.open_local_request",
            return_value=response,
        ),
        patch(
            "free_claude_code.cli.launchers.common.package_version",
            return_value="4.30.26",
        ),
    ):
        error = preflight_proxy("http://127.0.0.1:8082")

    assert error == "FCC version mismatch: running unknown, installed 4.30.26"
    assert is_proxy_version_mismatch(error)


def test_server_entrypoint_reports_stale_fcc_without_port_misclassification(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from free_claude_code.cli import commands, entrypoints

    settings = Settings.model_construct(
        host="0.0.0.0",
        port=8082,
        anthropic_auth_token="freecc",
        model="opencode_go/muse-spark-1.2-contributor",
    )
    mismatch = "FCC version mismatch: running 4.30.25, installed 4.30.26"
    with (
        patch.object(commands, "load_server_settings", return_value=settings),
        patch(
            "free_claude_code.cli.launchers.common.preflight_proxy",
            return_value=mismatch,
        ),
        patch.object(entrypoints, "_server_port_is_occupied") as port_probe,
        patch.object(commands, "serve") as run_server,
        pytest.raises(SystemExit) as exc_info,
    ):
        entrypoints._run_server_entrypoint()

    assert exc_info.value.code == 1
    port_probe.assert_not_called()
    run_server.assert_not_called()
    error = capsys.readouterr().err
    assert mismatch in error
    assert "Stop the existing FCC daemon" in error
