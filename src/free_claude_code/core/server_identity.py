"""Credential-free identity and lifecycle metadata for one FCC server process."""

import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol


class ServerSettings(Protocol):
    """Minimal settings contract needed for public server identity metadata."""

    host: str
    port: int


SERVER_SERVICE_NAME = "agentswitchboard"
SERVER_HEALTH_PROTOCOL = 1
SERVER_MODE_ENV = "FCC_SERVER_MODE"
_START_MONOTONIC = time.monotonic()
_STARTED_AT = datetime.now(UTC).isoformat(timespec="seconds")
_INSTANCE_ID = uuid.uuid4().hex


def server_mode() -> str:
    """Return the non-secret deployment mode advertised to local clients."""

    return os.environ.get(SERVER_MODE_ENV, "standard").strip() or "standard"


def _local_host_for_urls(host: str) -> str:
    """Return a loopback-displayable host fragment for local clients."""

    value = host.strip() if host else "127.0.0.1"
    if value in {"0.0.0.0", "::", "[::]"}:
        value = "127.0.0.1"
    if ":" in value and not value.startswith("["):
        value = f"[{value}]"
    return value


def server_identity_payload(
    settings: ServerSettings, *, lifecycle: str = "running"
) -> dict[str, Any]:
    """Build the shared health/Admin identity payload for the current process."""

    proxy_url = f"http://{_local_host_for_urls(settings.host)}:{settings.port}"
    return {
        "service": SERVER_SERVICE_NAME,
        "protocol": SERVER_HEALTH_PROTOCOL,
        "instance_id": _INSTANCE_ID,
        "pid": os.getpid(),
        "mode": server_mode(),
        "lifecycle": lifecycle,
        "started_at": _STARTED_AT,
        "uptime_seconds": max(0.0, round(time.monotonic() - _START_MONOTONIC, 3)),
        "host": settings.host,
        "port": settings.port,
        "health_url": f"{proxy_url}/health",
        "admin_url": f"{proxy_url}/admin",
    }
