"""Deterministic contracts for the real-device browser canary wrapper."""

import base64
import threading
from collections.abc import Mapping
from typing import Any

import pytest

from smoke.lib.codex_browser_device import run_browser_device_smoke


class _FakeBrowser:
    def __init__(self, *, bad_snapshot: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.bad_snapshot = bad_snapshot

    def execute(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        cancel_event: threading.Event,
    ) -> Mapping[str, Any]:
        assert cancel_event.is_set() is False
        self.calls.append((operation, dict(arguments)))
        if operation == "list_tabs":
            return {"family": "chrome", "tabs": [{"id": "existing-secret-id"}]}
        if operation == "new_tab":
            return {"id": "disposable-secret-id", "url": "about:blank"}
        if operation == "goto":
            return {"id": "disposable-secret-id"}
        if operation == "snapshot":
            return {"text": "" if self.bad_snapshot else "private snapshot text"}
        if operation == "screenshot":
            return {
                "media_type": "image/jpeg",
                "image_base64": base64.b64encode(b"jpeg-bytes").decode("ascii"),
            }
        if operation == "close_tab":
            return {"ok": True}
        raise AssertionError(f"unexpected operation: {operation}")


def test_device_smoke_returns_only_metadata_and_closes_disposable_tab() -> None:
    browser = _FakeBrowser()

    receipt = run_browser_device_smoke(browser, family="chrome")

    assert receipt["schema"] == "fcc.codex-browser-device.v1"
    assert receipt["evidence"] == "real-device-local"
    assert receipt["existing_tab_count"] == 1
    assert receipt["snapshot_chars"] == len("private snapshot text")
    assert receipt["screenshot_bytes"] == len(b"jpeg-bytes")
    assert receipt["provider_model_calls"] == 0
    serialized = repr(receipt)
    assert "disposable-secret-id" not in serialized
    assert "existing-secret-id" not in serialized
    assert "private snapshot text" not in serialized
    assert base64.b64encode(b"jpeg-bytes").decode("ascii") not in serialized
    assert browser.calls[-1] == (
        "close_tab",
        {"tab_id": "disposable-secret-id"},
    )


def test_device_smoke_closes_tab_when_snapshot_fails() -> None:
    browser = _FakeBrowser(bad_snapshot=True)

    with pytest.raises(ValueError, match="snapshot"):
        run_browser_device_smoke(browser, family="chrome")

    assert browser.calls[-1] == (
        "close_tab",
        {"tab_id": "disposable-secret-id"},
    )
