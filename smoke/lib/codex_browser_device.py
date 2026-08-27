"""Metadata-only real-device canary for the installed Codex browser plugin."""

from __future__ import annotations

import base64
import hashlib
import threading
from collections.abc import Mapping
from typing import Any, Protocol


class BrowserAdapter(Protocol):
    def execute(
        self,
        operation: str,
        arguments: Mapping[str, Any],
        cancel_event: threading.Event,
    ) -> Mapping[str, Any]: ...


def run_browser_device_smoke(
    adapter: BrowserAdapter,
    *,
    family: str,
    url: str = "data:text/html,<title>FCC Browser Smoke</title><main>FCC browser smoke</main>",
) -> dict[str, Any]:
    """Create a disposable tab, inspect it, screenshot it, and close it.

    The returned receipt never contains the tab id, URL, snapshot text, or image
    bytes. This is a local device/backend canary, not a provider/model request.
    """

    cancel = threading.Event()
    listed = adapter.execute("list_tabs", {}, cancel)
    tabs = listed.get("tabs")
    if not isinstance(tabs, list):
        raise ValueError("browser list_tabs result did not contain a tab list")

    created = adapter.execute("new_tab", {}, cancel)
    tab_id = created.get("id")
    if not isinstance(tab_id, str) or not tab_id:
        raise ValueError("browser new_tab result did not contain a tab id")

    closed = False
    try:
        adapter.execute("goto", {"tab_id": tab_id, "url": url}, cancel)
        snapshot = adapter.execute(
            "snapshot",
            {"tab_id": tab_id, "disable_diffing": True},
            cancel,
        )
        snapshot_text = snapshot.get("text")
        if not isinstance(snapshot_text, str) or not snapshot_text:
            raise ValueError("browser snapshot did not return bounded text")

        screenshot = adapter.execute(
            "screenshot",
            {"tab_id": tab_id, "full_page": False},
            cancel,
        )
        media_type = screenshot.get("media_type")
        encoded = screenshot.get("image_base64")
        if media_type != "image/jpeg" or not isinstance(encoded, str) or not encoded:
            raise ValueError("browser screenshot did not return a JPEG payload")
        try:
            screenshot_bytes = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("browser screenshot payload was not valid base64") from exc
        if not screenshot_bytes:
            raise ValueError("browser screenshot payload was empty")

        return {
            "schema": "fcc.codex-browser-device.v1",
            "evidence": "real-device-local",
            "family": family,
            "existing_tab_count": len(tabs),
            "disposable_tab_created": True,
            "tab_id_hash": hashlib.sha256(tab_id.encode("utf-8")).hexdigest(),
            "snapshot_chars": len(snapshot_text),
            "screenshot_media_type": media_type,
            "screenshot_bytes": len(screenshot_bytes),
            "provider_model_calls": 0,
        }
    finally:
        try:
            adapter.execute("close_tab", {"tab_id": tab_id}, cancel)
            closed = True
        finally:
            if not closed:
                cancel.set()
