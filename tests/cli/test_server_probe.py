"""Identity-aware local FCC server probe tests."""

import json
import threading
from unittest.mock import MagicMock, patch

from free_claude_code.cli.launchers.common import probe_server
from free_claude_code.cli.terminal_control import _wait_for_proxy
from free_claude_code.config.settings import Settings


def _response(payload: object, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.getcode.return_value = status
    response.read.return_value = json.dumps(payload).encode("utf-8")
    return response


def test_probe_server_accepts_matching_fcc_identity_and_mode() -> None:
    response = _response(
        {
            "service": "agentswitchboard",
            "protocol": 1,
            "mode": "sandbox",
            "instance_id": "abc",
        }
    )
    transport = MagicMock()
    transport.__enter__.return_value = response

    with patch(
        "free_claude_code.cli.launchers.common.open_local_request",
        return_value=transport,
    ):
        result = probe_server("http://127.0.0.1:8083", expected_mode="sandbox")

    assert result.healthy is True
    assert result.payload["instance_id"] == "abc"
    assert result.foreign is False


def test_probe_server_rejects_foreign_health_service() -> None:
    response = _response({"status": "healthy", "version": "other"})
    transport = MagicMock()
    transport.__enter__.return_value = response

    with patch(
        "free_claude_code.cli.launchers.common.open_local_request",
        return_value=transport,
    ):
        result = probe_server("http://127.0.0.1:8083", expected_mode="sandbox")

    assert result.healthy is False
    assert result.foreign is True
    assert result.error is not None
    assert "identity" in result.error


def test_owned_readiness_keeps_polling_after_wrong_mode_response() -> None:
    settings = Settings.model_construct(host="127.0.0.1", port=8083)
    worker = MagicMock(spec=threading.Thread)
    worker.is_alive.return_value = True
    preflight = MagicMock(side_effect=["foreign service: wrong mode", None])

    with (
        patch("free_claude_code.cli.terminal_control.preflight_proxy", preflight),
        patch("free_claude_code.cli.terminal_control.time.sleep"),
    ):
        error = _wait_for_proxy(
            settings,
            worker,
            timeout=1,
            expected_mode="sandbox",
        )

    assert error is None
    assert preflight.call_args_list[0].kwargs == {"expected_mode": "sandbox"}


def test_probe_server_rejects_mode_mismatch() -> None:
    response = _response(
        {"service": "agentswitchboard", "protocol": 1, "mode": "standard"}
    )
    transport = MagicMock()
    transport.__enter__.return_value = response

    with patch(
        "free_claude_code.cli.launchers.common.open_local_request",
        return_value=transport,
    ):
        result = probe_server("http://127.0.0.1:8083", expected_mode="sandbox")

    assert result.healthy is False
    assert result.foreign is True
    assert result.error is not None
    assert "expected FCC mode 'sandbox'" in result.error
