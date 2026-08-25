"""Small loopback-only client for FCC's canonical Admin API."""

import json
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

from free_claude_code.cli.local_http import open_local_request
from free_claude_code.config.server_urls import local_proxy_root_url
from free_claude_code.config.settings import Settings

ADMIN_REQUEST_TIMEOUT_SECONDS = 5.0


class LocalAdminError(RuntimeError):
    """Raised when the local Admin API cannot complete a terminal action."""


def get_admin_config(settings: Settings) -> dict[str, Any]:
    """Return the canonical Admin config manifest and effective values."""

    return _request_json(settings, "/admin/api/config")


def apply_admin_values(
    settings: Settings,
    values: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and apply one partial config update through the Admin API."""

    payload = {"values": dict(values)}
    validation = _request_json(
        settings,
        "/admin/api/config/validate",
        method="POST",
        payload=payload,
    )
    if validation.get("valid") is not True:
        return validation | {"applied": False}
    return _request_json(
        settings,
        "/admin/api/config/apply",
        method="POST",
        payload=payload,
    )


def _request_json(
    settings: Settings,
    path: str,
    *,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{local_proxy_root_url(settings)}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with open_local_request(request, timeout=ADMIN_REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except HTTPError as exc:
        raise LocalAdminError(f"Admin request returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise LocalAdminError(f"Admin request failed: {exc.reason}") from exc
    except OSError as exc:
        raise LocalAdminError(f"Admin request failed: {type(exc).__name__}") from exc

    try:
        decoded = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalAdminError("Admin response was not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise LocalAdminError("Admin response must be a JSON object")
    return decoded
