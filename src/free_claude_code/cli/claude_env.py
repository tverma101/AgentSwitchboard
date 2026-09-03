"""Shared Claude Code environment policy for FCC client surfaces."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from free_claude_code.cli.claude_firewall import (
    CLAUDE_PROCESS_WRAPPER_ENV,
    default_process_wrapper_path,
)
from free_claude_code.cli.local_http import with_local_proxy_bypass
from free_claude_code.cli.proxy_auth import proxy_auth_token
from free_claude_code.config.model_refs import (
    normalize_model_ref,
    parse_model_context_windows,
)
from free_claude_code.core.server_identity import server_mode

CLAUDE_CONTEXT_CAP_DEFAULT = 256_000
CLAUDE_CONTEXT_CAP_MIN = 32_000
CLAUDE_CONTEXT_CAP_MAX = 1_000_000
CLAUDE_CONTEXT_CAP_ENV = "FCC_CLAUDE_CONTEXT_TOKENS"
MODEL_CONTEXT_WINDOWS_ENV = "MODEL_CONTEXT_WINDOWS"
CLAUDE_BINARY_NAME = "claude"
CLAUDE_DISABLE_NONSTREAMING_FALLBACK_ENV = "CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK"

# Retained as compatibility constants for callers that inspect older FCC
# policy names. The launcher does not inject these client-owned settings.
CLAUDE_MCP_OUTPUT_TOKENS_DEFAULT = 12_000
CLAUDE_MCP_OUTPUT_TOKENS_ENV = "MAX_MCP_OUTPUT_TOKENS"

# Claude Code disables deferred MCP tool loading when it is pointed at a
# non-first-party base URL. FCC handles the search-only protocol blocks at its
# provider boundary, so opt the child client back into deferred registration by
# default while preserving an explicit client setting.
CLAUDE_TOOL_SEARCH_DEFAULT = "true"
CLAUDE_TOOL_SEARCH_ENV = "ENABLE_TOOL_SEARCH"

CLAUDE_EFFORT_LEVEL_ENV = "CLAUDE_CODE_EFFORT_LEVEL"
CLAUDE_EFFORT_FLAG = "--effort"
# ``xhigh`` is the strongest effort value Claude Code can transmit through
# the remote gateway. Native ``ultracode`` also requires client-only workflow
# state and must not be advertised by the FCC launcher.
CLAUDE_EFFORT_DEFAULT = "xhigh"

# Keys Claude Code applies from its settings.json ``env`` block over the
# process environment. FCC's launcher owns these for a proxy session; when a
# user settings file sets any of them, Claude Code would silently override the
# launcher's routing/auth and bypass the FCC gateway. FCC fails closed instead.
SETTINGS_ENV_ROUTING_KEYS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
)
_CLAUDE_SETTING_SOURCES = frozenset({"user", "project", "local"})

# Optional hard native ceilings for models known to support less than the FCC
# default. Do not put advertised large windows here: FCC intentionally treats a
# 1M-capable gateway model as 256K unless the user explicitly opts higher.
MODEL_CONTEXT_WINDOWS: dict[str, int] = {}


def context_cap_tokens(base_env: Mapping[str, str]) -> int:
    """Parse the legacy FCC context value without applying it to a launch.

    This helper remains for backwards-compatible settings/UI readers. The
    current launcher deliberately does not call it when constructing the child
    environment.
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


def model_context_window(
    model_id: str | None,
    context_windows: Mapping[str, int] | None = None,
) -> int | None:
    """Return the exact configured context window for ``model_id``, if any."""

    if not model_id:
        return None
    normalized = normalize_model_ref(model_id)
    if normalized.virtual_context_window is not None:
        return normalized.virtual_context_window
    windows = MODEL_CONTEXT_WINDOWS if context_windows is None else context_windows
    return windows.get(normalized.model_ref)


def effective_context_window(
    model_id: str | None,
    base_env: Mapping[str, str],
    context_windows: Mapping[str, int] | None = None,
) -> int:
    """Return the configured context window or the legacy default."""

    configured_cap = context_cap_tokens(base_env)
    native_ceiling = model_context_window(model_id, context_windows)
    if native_ceiling is None:
        return configured_cap
    return min(configured_cap, native_ceiling)


def configured_context_windows(
    base_env: Mapping[str, str],
) -> dict[str, int]:
    """Parse the optional per-model context map from the child environment."""

    raw = base_env.get(MODEL_CONTEXT_WINDOWS_ENV, "")
    try:
        return parse_model_context_windows(raw)
    except ValueError:
        # Settings validation rejects malformed values before a normal launch.
        # Keep this helper safe for direct callers and inherited environments.
        return {}


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


def claude_settings_env(
    base_env: Mapping[str, str],
    *,
    cwd: str | Path | None = None,
    argv: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return merged env blocks from Claude's active settings layers."""

    merged: dict[str, Any] = {}
    for _source, env in _settings_env_sources(base_env, cwd=cwd, argv=argv):
        merged.update(env)
    return merged


def conflicting_settings_env_keys(
    base_env: Mapping[str, str],
    *,
    cwd: str | Path | None = None,
    argv: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Return FCC-routing keys that any active Claude setting would override."""

    env = claude_settings_env(base_env, cwd=cwd, argv=argv)
    return tuple(key for key in SETTINGS_ENV_ROUTING_KEYS if key in env)


def settings_env_routing_conflict_message(
    base_env: Mapping[str, str],
    *,
    cwd: str | Path | None = None,
    argv: Sequence[str] | None = None,
) -> str | None:
    """Return the user-facing error for a settings-based routing override."""

    conflicts = conflicting_settings_env_keys(base_env, cwd=cwd, argv=argv)
    if not conflicts:
        return None
    keys = ", ".join(conflicts)
    sources = _conflicting_settings_sources(base_env, cwd=cwd, argv=argv)
    source_text = "; ".join(
        f"{source}: {', '.join(source_keys)}" for source, source_keys in sources
    )
    return (
        "Free Claude Code proxy routing is overridden by Claude "
        f"settings env keys: {keys} ({source_text}). Remove these keys from "
        "the active settings env block or --settings overlay so the FCC "
        "launcher can route through the local proxy."
    )


def _settings_env_sources(
    base_env: Mapping[str, str],
    *,
    cwd: str | Path | None,
    argv: Sequence[str] | None,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Return active Claude setting env blocks in precedence order."""

    sources = _setting_sources(argv)
    config_dir = Path(base_env.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    project_dir = Path(cwd) if cwd is not None else Path.cwd()
    paths: list[tuple[str, Path]] = []
    if "user" in sources:
        paths.append(("user settings.json", config_dir / "settings.json"))
    if "project" in sources:
        paths.append(
            ("project .claude/settings.json", project_dir / ".claude" / "settings.json")
        )
    if "local" in sources:
        paths.append(
            (
                "local .claude/settings.local.json",
                project_dir / ".claude" / "settings.local.json",
            )
        )

    loaded: list[tuple[str, dict[str, Any]]] = []
    for label, path in paths:
        env = _settings_env_from_document(_read_settings_document(path))
        if env:
            loaded.append((label, env))

    for value in _settings_overlays(argv):
        env = _settings_env_from_document(_read_settings_overlay(value))
        if env:
            loaded.append(("--settings overlay", env))
    return tuple(loaded)


def _conflicting_settings_sources(
    base_env: Mapping[str, str],
    *,
    cwd: str | Path | None,
    argv: Sequence[str] | None,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return source labels and routing keys, never configured values."""

    conflicts: list[tuple[str, tuple[str, ...]]] = []
    for source, env in _settings_env_sources(base_env, cwd=cwd, argv=argv):
        keys = tuple(key for key in SETTINGS_ENV_ROUTING_KEYS if key in env)
        if keys:
            conflicts.append((source, keys))
    return tuple(conflicts)


def _setting_sources(argv: Sequence[str] | None) -> frozenset[str]:
    """Resolve Claude's optional setting-source filter from launcher arguments."""

    selected = _CLAUDE_SETTING_SOURCES
    args = tuple(argv or ())
    for index, arg in enumerate(args):
        value: str | None = None
        if arg == "--setting-sources" and index + 1 < len(args):
            value = args[index + 1]
        elif arg.startswith("--setting-sources="):
            value = arg.split("=", 1)[1]
        if value is None:
            continue
        parsed = frozenset(item.strip() for item in value.split(",") if item.strip())
        selected = parsed & _CLAUDE_SETTING_SOURCES
    return selected


def _settings_overlays(argv: Sequence[str] | None) -> tuple[str, ...]:
    """Return values supplied to Claude's repeatable ``--settings`` flag."""

    values: list[str] = []
    args = tuple(argv or ())
    for index, arg in enumerate(args):
        if arg == "--settings" and index + 1 < len(args):
            values.append(args[index + 1])
        elif arg.startswith("--settings="):
            values.append(arg.split("=", 1)[1])
    return tuple(value for value in values if value and not value.startswith("--"))


def _read_settings_document(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _read_settings_overlay(value: str) -> dict[str, Any]:
    path = Path(value).expanduser()
    if path.is_file():
        return _read_settings_document(path)
    try:
        parsed = json.loads(value)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _settings_env_from_document(document: Mapping[str, Any]) -> dict[str, Any]:
    env = document.get("env")
    if not isinstance(env, dict):
        return {}
    return {key: value for key, value in env.items() if isinstance(key, str)}


def claude_effort_environment(
    argv: Sequence[str], base_env: Mapping[str, str]
) -> dict[str, str]:
    """Add the strongest supported remote effort unless the client chose one.

    Native ``ultracode`` is a Claude Code client-session mode that cannot be
    created by an Anthropic-compatible gateway. ``xhigh`` is the valid remote
    effort value and is translated by FCC at its provider boundary.
    """

    environment = dict(base_env)
    if any(
        argument == CLAUDE_EFFORT_FLAG or argument.startswith(f"{CLAUDE_EFFORT_FLAG}=")
        for argument in argv
    ):
        return environment
    if environment.get(CLAUDE_EFFORT_LEVEL_ENV, "").strip():
        return environment
    environment[CLAUDE_EFFORT_LEVEL_ENV] = CLAUDE_EFFORT_DEFAULT
    return environment


def build_claude_proxy_env(
    *,
    proxy_root_url: str,
    auth_token: str,
    base_env: Mapping[str, str],
    model_id: str | None = None,
    context_windows: Mapping[str, int] | None = None,
    process_wrapper_path: str | None = None,
) -> dict[str, str]:
    """Return the canonical environment for Claude Code proxy sessions.

    FCC owns only the loopback proxy transport and authentication boundary in
    standard mode. The sandbox intentionally restores its audited 256K Claude
    window contract; context governance, MCP output, and tool-search policy
    remain client-owned in both modes. Explicit client values are preserved
    except for the sandbox-owned context-window pair.
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
    # Claude 2.1.22x gates gateway /v1/models behind provider mode as well as
    # the discovery flag. FCC owns both the base URL and static proxy token for
    # this child, so mark the session as a gateway session explicitly.
    env["CLAUDE_CODE_USE_GATEWAY"] = "1"
    env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] = "1"
    # Claude owns the loop, but FCC owns retry/replay at the gateway boundary.
    # Do not let Claude independently replay a failed streaming request through
    # its non-streaming fallback after provider-visible work may have started.
    env[CLAUDE_DISABLE_NONSTREAMING_FALLBACK_ENV] = "1"

    configured_window = model_context_window(model_id, context_windows)
    if server_mode() == "sandbox":
        # The sandbox deliberately keeps the former narrow Claude window
        # contract for controlled testing. Do not re-enable the broader FCC
        # context governor or MCP/tool-search policy here.
        window = effective_context_window(model_id, base_env, context_windows)
        env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(window)
        env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(window)
    elif configured_window is not None:
        # Standard launches remain client-owned unless an exact model mapping
        # explicitly opts into a context budget.
        window = str(configured_window)
        env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = window
        env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = window

    env[CLAUDE_PROCESS_WRAPPER_ENV] = process_wrapper_path or str(
        default_process_wrapper_path(base_env)
    )

    env["DISABLE_AUTOUPDATER"] = "1"
    env["DISABLE_FEEDBACK_COMMAND"] = "1"
    env["DISABLE_ERROR_REPORTING"] = "1"
    return env
