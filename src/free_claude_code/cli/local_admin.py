"""Small loopback-only client for FCC's canonical Admin API."""

import json
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request

from free_claude_code.application.connected_accounts import ConnectedAccountLoginMode
from free_claude_code.cli.local_http import open_local_request
from free_claude_code.config.server_urls import local_proxy_root_url
from free_claude_code.config.settings import Settings

ADMIN_REQUEST_TIMEOUT_SECONDS = 5.0


class LocalAdminError(RuntimeError):
    """Raised when the local Admin API cannot complete a terminal action."""


def get_admin_config(settings: Settings) -> dict[str, Any]:
    """Return the canonical Admin config manifest and effective values."""

    return _request_json(settings, "/admin/api/config")


def get_admin_status(settings: Settings) -> dict[str, Any]:
    """Return the canonical local server status snapshot."""

    return _request_json(settings, "/admin/api/status")


def get_models(settings: Settings, *, refresh: bool = False) -> dict[str, Any]:
    """Return configured and cached models, optionally refreshing explicitly."""

    path = "/admin/api/models/refresh" if refresh else "/admin/api/models"
    return _request_json(settings, path, method="POST" if refresh else "GET")


def get_usage(settings: Settings, *, days: int = 30) -> dict[str, Any]:
    """Return the metadata-only local usage summary."""

    if days < 1 or days > 366:
        raise ValueError("usage range must be between 1 and 366 days")
    return _request_json(settings, f"/admin/api/usage?days={days}")


def get_local_provider_status(settings: Settings) -> dict[str, Any]:
    """Probe explicitly requested local providers through the Admin API."""

    return _request_json(settings, "/admin/api/providers/local-status")


def test_provider(settings: Settings, provider_id: str) -> dict[str, Any]:
    """Run the canonical provider model-list test for one selected provider."""

    return _request_json(
        settings,
        f"/admin/api/providers/{quote(provider_id, safe='')}/test",
        method="POST",
    )


def apply_custom_provider(
    settings: Settings,
    values: Mapping[str, Any],
    *,
    existing_provider_id: str | None = None,
) -> dict[str, Any]:
    """Create or update a custom provider through the canonical Admin API."""

    if existing_provider_id is None:
        path = "/admin/api/custom-providers"
        method = "POST"
    else:
        path = f"/admin/api/custom-providers/{quote(existing_provider_id, safe='')}"
        method = "PUT"
    return _request_json(settings, path, method=method, payload=dict(values))


def remove_custom_provider(settings: Settings, provider_id: str) -> dict[str, Any]:
    """Remove one custom provider through the canonical Admin API."""

    return _request_json(
        settings,
        f"/admin/api/custom-providers/{quote(provider_id, safe='')}",
        method="DELETE",
    )


def route_diagnostic(
    settings: Settings,
    *,
    model: str | None = None,
    shapes: tuple[str, ...] = ("text",),
    mode: str = "strict",
) -> dict[str, Any]:
    """Explain a synthetic route without sending a provider request."""

    payload: dict[str, Any] = {"shapes": shapes, "mode": mode}
    if model:
        payload["model"] = model
    return _request_json(
        settings,
        "/admin/api/diagnostics/route",
        method="POST",
        payload=payload,
    )


def connected_account_status(settings: Settings, provider_id: str) -> dict[str, Any]:
    """Return credential-free status for one connected-account provider."""

    return _request_json(
        settings,
        f"/admin/api/providers/{quote(provider_id, safe='')}/auth",
    )


def start_connected_account_login(
    settings: Settings,
    provider_id: str,
    mode: ConnectedAccountLoginMode,
) -> dict[str, Any]:
    """Start an explicitly selected browser or device login flow."""

    return _request_json(
        settings,
        f"/admin/api/providers/{quote(provider_id, safe='')}/auth/login",
        method="POST",
        payload={"mode": mode.value},
    )


def cancel_connected_account_login(
    settings: Settings, provider_id: str
) -> dict[str, Any]:
    """Cancel a pending connected-account login."""

    return _request_json(
        settings,
        f"/admin/api/providers/{quote(provider_id, safe='')}/auth/cancel",
        method="POST",
    )


def disconnect_connected_account(
    settings: Settings, provider_id: str
) -> dict[str, Any]:
    """Disconnect a connected account through its canonical owner."""

    return _request_json(
        settings,
        f"/admin/api/providers/{quote(provider_id, safe='')}/auth",
        method="DELETE",
    )


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
        with open_local_request(
            request,
            timeout=ADMIN_REQUEST_TIMEOUT_SECONDS,
        ) as response:
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
