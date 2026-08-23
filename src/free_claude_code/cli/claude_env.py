"""Shared Claude Code environment policy for FCC client surfaces."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from free_claude_code.cli.local_http import with_local_proxy_bypass
from free_claude_code.cli.proxy_auth import proxy_auth_token

CLAUDE_CONTEXT_CAP_DEFAULT = 256_000
CLAUDE_CONTEXT_CAP_MIN = 32_000
CLAUDE_CONTEXT_CAP_MAX = 1_000_000
CLAUDE_CONTEXT_CAP_ENV = "FCC_CLAUDE_CONTEXT_TOKENS"
CLAUDE_BINARY_NAME = "claude"

# Optional hard native ceilings for models known to support less than the FCC
# default. Do not put advertised large windows here: FCC intentionally treats a
# 1M-capable gateway model as 256K unless the user explicitly opts higher.
MODEL_CONTEXT_WINDOWS: dict[str, int] = {}


def context_cap_tokens(base_env: Mapping[str, str]) -> int:
    """Return FCC's effective Claude context cap for this launch.

    The default is deliberately 256K even when an upstream gateway advertises
    a larger window. An explicit ``FCC_CLAUDE_CONTEXT_TOKENS`` override may
    choose a value from 32K through 1M; malformed/out-of-range values fail safe
    to the 256K default instead of silently creating an extreme window.
    """

    raw = base_env.get(CLAUDE_CONTEXT_CAP_ENV)
    if raw is None or not raw.strip():
        return CLAUDE_CONTEXT_CAP_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        return CLAUDE_CONTEXT_CAP_DEFAULT
    if not CLAUDE_CONTEXT_CAP_MIN <= value <= CLAUDE_CONTEXT_CAP_MAX:
        return CLAUDE_CONTEXT_CAP_DEFAULT
    return value


def model_context_window(model_id: str | None) -> int | None:
    """Return a known native context ceiling for ``model_id``, if any."""

    if not model_id:
        return None
    lowered = model_id.lower()
    for needle, window in MODEL_CONTEXT_WINDOWS.items():
        if needle in lowered:
            return window
    return None


def effective_context_window(
    model_id: str | None,
    base_env: Mapping[str, str],
) -> int:
    """Return the launch cap, respecting a known smaller native model ceiling."""

    configured_cap = context_cap_tokens(base_env)
    native_ceiling = model_context_window(model_id)
    if native_ceiling is None:
        return configured_cap
    return min(configured_cap, native_ceiling)


def resolved_model_id(
    argv: Sequence[str] | None, base_env: Mapping[str, str]
) -> str | None:
    """Resolve the Claude Code model from argv, env, then saved settings."""

    for index, arg in enumerate(argv or ()):
        if arg in ("--model", "-m") and index + 1 < len(argv or ()):
            return (argv or ())[index + 1]
        if arg.startswith("--model="):
            return arg.split("=", 1)[1]
    model = base_env.get("CLAUDE_MODEL")
    if model:
        return model
    config_dir = Path(base_env.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    try:
        settings = json.loads((config_dir / "settings.json").read_text())
    except OSError, ValueError:
        return None
    model = settings.get("model")
    return model if isinstance(model, str) else None


def build_claude_proxy_env(
    *,
    proxy_root_url: str,
    auth_token: str,
    base_env: Mapping[str, str],
    model_id: str | None = None,
) -> dict[str, str]:
    """Return the canonical environment for Claude Code proxy sessions.

    FCC owns the gateway context policy. Claude Code is told to treat the
    session as 256K by default even when the upstream model advertises 1M.
    ``FCC_CLAUDE_CONTEXT_TOKENS`` is the single user-facing override.
    """

    # Claude's aggregate traffic flag also suppresses gateway model discovery.
    env = with_local_proxy_bypass(
        {
            key: value
            for key, value in base_env.items()
            if not key.startswith("ANTHROPIC_")
            and key != "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"
        },
        proxy_root_url=proxy_root_url,
    )
    env["ANTHROPIC_BASE_URL"] = proxy_root_url
    env["ANTHROPIC_AUTH_TOKEN"] = proxy_auth_token(auth_token)
    env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] = "1"

    window = effective_context_window(model_id, base_env)
    env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(window)
    env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(window)
    # Recent Claude Code releases enforce a separate hardcoded 200K window for
    # unknown third-party models. FCC already supplies an explicit bounded cap,
    # so that second enforcement layer is both redundant and destabilizing.
    env["CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"] = "1"

    env["DISABLE_AUTOUPDATER"] = "1"
    env["DISABLE_FEEDBACK_COMMAND"] = "1"
    env["DISABLE_ERROR_REPORTING"] = "1"
    return env
