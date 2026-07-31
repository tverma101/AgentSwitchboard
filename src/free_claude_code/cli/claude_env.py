"""Shared Claude Code environment policy for FCC client surfaces."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from free_claude_code.cli.local_http import with_local_proxy_bypass
from free_claude_code.cli.proxy_auth import proxy_auth_token

CLAUDE_CODE_AUTO_COMPACT_WINDOW = "190000"
CLAUDE_BINARY_NAME = "claude"

# Per-model context-window overrides (tokens) advertised to Claude Code for
# FCC gateway models. Claude Code assumes unknown gateway models have a 200K
# window and auto-compacts near that by default; these models natively support
# far larger contexts (DeepSeek V4 Flash: 1M), so matching models get both
# CLAUDE_CODE_MAX_CONTEXT_TOKENS (the believed model window, honored for
# non-"claude-" model IDs) and CLAUDE_CODE_AUTO_COMPACT_WINDOW raised to the
# configured window. Keys are substrings matched against the resolved model ID.
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "deepseek-v4-flash": 400000,
}


def model_context_window(model_id: str | None) -> int | None:
    """Return the context-window override for ``model_id``, or None."""

    if not model_id:
        return None
    lowered = model_id.lower()
    for needle, window in MODEL_CONTEXT_WINDOWS.items():
        if needle in lowered:
            return window
    return None


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
    config_dir = Path(
        base_env.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")
    )
    try:
        settings = json.loads((config_dir / "settings.json").read_text())
    except (OSError, ValueError):
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

    ``model_id`` is the resolved Claude Code model for the session. When it
    matches an entry in ``MODEL_CONTEXT_WINDOWS``, the session's auto-compact
    window and believed model window are raised to that entry's token count;
    otherwise the default 190K compact window is used unchanged.
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
    env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = CLAUDE_CODE_AUTO_COMPACT_WINDOW
    env["DISABLE_AUTOUPDATER"] = "1"
    env["DISABLE_FEEDBACK_COMMAND"] = "1"
    env["DISABLE_ERROR_REPORTING"] = "1"
    window = model_context_window(model_id)
    if window is not None:
        env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(window)
        env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(window)
    return env
