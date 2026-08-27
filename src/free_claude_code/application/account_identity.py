"""Credential-free local identity summaries for the terminal home surface."""

import base64
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from free_claude_code.config.paths import openai_auth_path


def fcc_provider_account_summary(path: Path | None = None) -> str:
    """Return FCC's local provider-account label without contacting OpenAI."""

    credential_path = path or openai_auth_path()
    try:
        payload = json.loads(credential_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "not connected"
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        return "needs attention"

    if not isinstance(payload, Mapping) or payload.get("version") != 1:
        return "needs attention"
    credentials = payload.get("credentials")
    if not isinstance(credentials, Mapping):
        return "needs attention"
    email = _jwt_email(credentials.get("id_token"))
    return email or "connected"


def _jwt_email(token: Any) -> str | None:
    if not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) < 2 or not parts[1]:
        return None
    encoded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    except ValueError, UnicodeDecodeError, json.JSONDecodeError:
        return None
    if not isinstance(decoded, Mapping):
        return None
    value = decoded.get("email")
    if not isinstance(value, str) or not value:
        profile = decoded.get("https://api.openai.com/profile")
        value = profile.get("email") if isinstance(profile, Mapping) else None
    return value if isinstance(value, str) and value else None
