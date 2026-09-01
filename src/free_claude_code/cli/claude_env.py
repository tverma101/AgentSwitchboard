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

CLAUDE_CONTEXT_CAP_DEFAULT = 256_000
CLAUDE_CONTEXT_CAP_MIN = 32_000
CLAUDE_CONTEXT_CAP_MAX = 1_000_000
CLAUDE_CONTEXT_CAP_ENV = "FCC_CLAUDE_CONTEXT_TOKENS"
CLAUDE_BINARY_NAME = "claude"
CLAUDE_DISABLE_NONSTREAMING_FALLBACK_ENV = "CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK"

# Claude Code applies this public limit to MCP tool results. Keep the default
# below the client warning threshold so a verbose local server cannot consume
# the whole conversation; preserve an explicit user value unchanged.
CLAUDE_MCP_OUTPUT_TOKENS_DEFAULT = 12_000
CLAUDE_MCP_OUTPUT_TOKENS_ENV = "MAX_MCP_OUTPUT_TOKENS"

# Claude Code disables deferred MCP tool loading when it is pointed at a
# non-first-party base URL. FCC handles the search-only protocol blocks at its
# provider boundary, so opt the child client back into deferred registration by
# default while preserving an explicit client setting.
CLAUDE_TOOL_SEARCH_DEFAULT = "true"
CLAUDE_TOOL_SEARCH_ENV = "ENABLE_TOOL_SEARCH"

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


def build_claude_proxy_env(
    *,
    proxy_root_url: str,
    auth_token: str,
    base_env: Mapping[str, str],
    model_id: str | None = None,
    process_wrapper_path: str | None = None,
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
    # Claude 2.1.22x gates gateway /v1/models behind provider mode as well as
    # the discovery flag. FCC owns both the base URL and static proxy token for
    # this child, so mark the session as a gateway session explicitly.
    env["CLAUDE_CODE_USE_GATEWAY"] = "1"
    env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] = "1"
    # Claude owns the loop, but FCC owns retry/replay at the gateway boundary.
    # Do not let Claude independently replay a failed streaming request through
    # its non-streaming fallback after provider-visible work may have started.
    env[CLAUDE_DISABLE_NONSTREAMING_FALLBACK_ENV] = "1"

    window = effective_context_window(model_id, base_env)
    env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(window)
    env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(window)
    # Do not disable Claude Code's unknown-model safety enforcement. Current
    # Claude Code uses that switch to wait for the API instead of proactively
    # compacting when a gateway model is not in its native model map. FCC has a
    # bounded window, but must still let the client compact before the boundary.
    env.pop("CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT", None)
    # Inherited compact-disable flags would defeat the bounded-session contract
    # and make the status line reach 100% before Claude can compact. The
    # automatic-only flag is separate from DISABLE_COMPACT in Claude Code.
    env.pop("DISABLE_COMPACT", None)
    env.pop("DISABLE_AUTO_COMPACT", None)
    env[CLAUDE_PROCESS_WRAPPER_ENV] = process_wrapper_path or str(
        default_process_wrapper_path(base_env)
    )

    # Do not inject Claude Code's private percentage override. Current Claude
    # versions compose it with the explicit gateway window in surprising ways,
    # and repeated compaction after rules/context reload is an upstream failure
    # mode. If a user explicitly supplies the variable, base_env preserves it.
    if not env.get(CLAUDE_MCP_OUTPUT_TOKENS_ENV, "").strip():
        env[CLAUDE_MCP_OUTPUT_TOKENS_ENV] = str(CLAUDE_MCP_OUTPUT_TOKENS_DEFAULT)
    if not env.get(CLAUDE_TOOL_SEARCH_ENV, "").strip():
        env[CLAUDE_TOOL_SEARCH_ENV] = CLAUDE_TOOL_SEARCH_DEFAULT

    env["DISABLE_AUTOUPDATER"] = "1"
    env["DISABLE_FEEDBACK_COMMAND"] = "1"
    env["DISABLE_ERROR_REPORTING"] = "1"
    return env
