"""Audited model profiles and wire helpers for Codex Responses-Lite.

Responses-Lite is a model-scoped Codex client dialect.  It is not a generic
replacement for the public Responses request shape, so callers must select a
profile explicitly before using these helpers.

The profile values below are a deliberately small snapshot of the public
Codex model catalog.  The full client ``instructions_template`` is not copied
here: it is mutable client/harness policy and transplanting it into a Claude
request would create the very prompt collision this adapter is intended to
avoid.  ``base_instructions`` is therefore a bounded compatibility overlay,
not a claim of full native Codex prompt parity.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

CODEX_RESPONSES_LITE_HEADER = "x-openai-internal-codex-responses-lite"
CODEX_FUNCTIONS_NAMESPACE = "functions"
CODEX_INSTALLATION_ID_KEY = "x-codex-installation-id"
CODEX_SESSION_ID_KEY = "session_id"
CODEX_THREAD_ID_KEY = "thread_id"
CODEX_TURN_ID_KEY = "turn_id"
CODEX_WINDOW_ID_KEY = "x-codex-window-id"
CODEX_TURN_METADATA_KEY = "x-codex-turn-metadata"
CODEX_PARENT_THREAD_ID_HEADER = "x-codex-parent-thread-id"
CODEX_SUBAGENT_HEADER = "x-openai-subagent"
CODEX_SESSION_ID_HEADER = "session-id"
CODEX_THREAD_ID_HEADER = "thread-id"
CODEX_INSTALLATION_ID_HEADER = "x-codex-installation-id"
CODEX_TURN_STATE_HEADER = "x-codex-turn-state"
CODEX_INSTALLATION_ID_FILENAME = "codex_installation_id"

CODEX_BASE_INSTRUCTIONS = (
    "You are Codex, a coding agent. Help the user understand, modify, test, "
    "and review code in their workspace. Follow the user's instructions, use "
    "tools when needed, and communicate concise progress and verification."
)

_SUPPORTED_REASONING_LEVELS = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True, slots=True)
class CodexModelProfile:
    """The stable model-specific fields needed by the Lite adapter."""

    model_id: str
    responses_lite: bool
    tool_mode: str
    shell_type: str
    multi_agent_version: str
    default_reasoning_level: str
    supported_reasoning_levels: tuple[str, ...]
    context_window: int
    max_context_window: int
    base_instructions: str = CODEX_BASE_INSTRUCTIONS


CODEX_MODEL_PROFILES: Mapping[str, CodexModelProfile] = MappingProxyType(
    {
        "gpt-5.6-luna": CodexModelProfile(
            model_id="gpt-5.6-luna",
            responses_lite=True,
            tool_mode="code_mode_only",
            shell_type="unified_exec",
            multi_agent_version="v1",
            default_reasoning_level="medium",
            supported_reasoning_levels=_SUPPORTED_REASONING_LEVELS,
            context_window=272_000,
            max_context_window=872_000,
        ),
        "gpt-5.6-sol": CodexModelProfile(
            model_id="gpt-5.6-sol",
            responses_lite=True,
            tool_mode="code_mode_only",
            shell_type="unified_exec",
            multi_agent_version="v2",
            default_reasoning_level="medium",
            supported_reasoning_levels=_SUPPORTED_REASONING_LEVELS,
            context_window=272_000,
            max_context_window=872_000,
        ),
        "gpt-5.6-terra": CodexModelProfile(
            model_id="gpt-5.6-terra",
            responses_lite=True,
            tool_mode="code_mode_only",
            shell_type="unified_exec",
            multi_agent_version="v2",
            default_reasoning_level="medium",
            supported_reasoning_levels=_SUPPORTED_REASONING_LEVELS,
            context_window=272_000,
            max_context_window=872_000,
        ),
    }
)


def codex_model_profile(model_id: str) -> CodexModelProfile | None:
    """Return the audited profile for one exact downstream model id."""

    return CODEX_MODEL_PROFILES.get(model_id.strip())


def responses_lite_tools(
    provider_tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Wrap ordinary function tools in Codex's default ``functions`` namespace."""

    if not provider_tools:
        return []
    return [
        {
            "type": "namespace",
            "name": CODEX_FUNCTIONS_NAMESPACE,
            "description": "",
            "tools": provider_tools,
        }
    ]


def codex_client_metadata(
    *,
    installation_id: str,
    session_id: str,
    thread_id: str,
    turn_id: str,
    window_id: str,
    parent_thread_id: str | None = None,
    subagent: str | None = None,
) -> dict[str, str]:
    """Build bounded Codex metadata from adapter-owned opaque identifiers.

    This mirrors the native ``CodexResponsesMetadata`` projections: the full
    turn blob travels as ``client_metadata["x-codex-turn-metadata"]`` while
    flat keys and direct HTTP headers are bounded compatibility projections of
    the same snapshot. FCC root turns omit ``parent_thread_id`` and
    ``subagent`` exactly like a native CLI root turn; Claude subagents share
    the same Codex thread and must not fake a native subagent identity.
    """

    import json

    turn_payload: dict[str, str] = {
        "installation_id": installation_id,
        "session_id": session_id,
        "thread_id": thread_id,
        "turn_id": turn_id,
        "window_id": window_id,
        "request_kind": "turn",
    }
    if parent_thread_id is not None:
        turn_payload["parent_thread_id"] = parent_thread_id
    if subagent is not None:
        turn_payload["subagent"] = subagent
    turn_metadata = json.dumps(
        turn_payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    metadata: dict[str, str] = {
        CODEX_INSTALLATION_ID_KEY: installation_id,
        CODEX_SESSION_ID_KEY: session_id,
        CODEX_THREAD_ID_KEY: thread_id,
        CODEX_TURN_ID_KEY: turn_id,
        CODEX_WINDOW_ID_KEY: window_id,
        CODEX_TURN_METADATA_KEY: turn_metadata,
    }
    if parent_thread_id is not None:
        metadata[CODEX_PARENT_THREAD_ID_HEADER] = parent_thread_id
    if subagent is not None:
        metadata[CODEX_SUBAGENT_HEADER] = subagent
    return metadata


def codex_session_headers(*, session_id: str, thread_id: str) -> dict[str, str]:
    """Return native ``build_session_headers`` projections for SSE transport."""

    return {
        CODEX_SESSION_ID_HEADER: session_id,
        CODEX_THREAD_ID_HEADER: thread_id,
    }


def codex_compatibility_headers(
    client_metadata: Mapping[str, str],
) -> dict[str, str]:
    """Return bounded native ``compatibility_headers`` projections.

    The header turn blob intentionally reuses the same bounded
    ``client_metadata`` blob: FCC never attaches the unbounded tool inventory
    that native strips from headers, so no second serialization is needed.
    """

    headers: dict[str, str] = {}
    window_id = client_metadata.get(CODEX_WINDOW_ID_KEY)
    if isinstance(window_id, str) and window_id:
        headers[CODEX_WINDOW_ID_KEY] = window_id
    turn_metadata = client_metadata.get(CODEX_TURN_METADATA_KEY)
    if isinstance(turn_metadata, str) and turn_metadata:
        headers[CODEX_TURN_METADATA_KEY] = turn_metadata
    parent_thread_id = client_metadata.get(CODEX_PARENT_THREAD_ID_HEADER)
    if isinstance(parent_thread_id, str) and parent_thread_id:
        headers[CODEX_PARENT_THREAD_ID_HEADER] = parent_thread_id
    subagent = client_metadata.get(CODEX_SUBAGENT_HEADER)
    if isinstance(subagent, str) and subagent:
        headers[CODEX_SUBAGENT_HEADER] = subagent
    return headers


def lite_item_id(prefix: str, value: Any, thread_id: str) -> str:
    """Return a stable thread-scoped ID for a prompt-only Lite item.

    Native Codex namespaces prompt-only item IDs with ``Uuid::new_v5`` under
    the session thread so retries and resumed sessions preserve identity
    without colliding across threads. Hashing the thread alongside the visible
    payload gives the same property without persisting UUID state.
    """

    import hashlib
    import json

    if isinstance(value, str):
        material = value.encode("utf-8")
    else:
        material = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    digest = hashlib.sha256(
        b"fcc-codex-lite-item-v1:" + thread_id.encode("utf-8") + b":" + material
    ).hexdigest()
    return f"{prefix}_{digest[:32]}"


def load_or_create_installation_id(
    config_dir: Any | None = None,
) -> str:
    """Return the stable Codex installation id, creating it once per config dir.

    Native Codex keeps one installation id per machine. FCC previously minted
    a fresh UUID per provider instance, which broke session affinity on every
    config reload. Persisting one opaque id under ``FCC_CONFIG_DIR`` restores
    the native stable-installation contract without storing credentials.
    """

    import os
    import uuid
    from pathlib import Path

    if config_dir is None:
        override = os.environ.get("FCC_CONFIG_DIR", "").strip()
        directory = Path(override).expanduser() if override else Path.home() / ".fcc"
    else:
        directory = Path(config_dir).expanduser()
    path = directory / CODEX_INSTALLATION_ID_FILENAME
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if (
        existing
        and len(existing) <= 256
        and all(0x21 <= ord(character) <= 0x7E for character in existing)
    ):
        return existing
    fresh = str(uuid.uuid4())
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(fresh + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    except OSError:
        return fresh
    return fresh


__all__ = [
    "CODEX_BASE_INSTRUCTIONS",
    "CODEX_FUNCTIONS_NAMESPACE",
    "CODEX_INSTALLATION_ID_FILENAME",
    "CODEX_INSTALLATION_ID_HEADER",
    "CODEX_INSTALLATION_ID_KEY",
    "CODEX_MODEL_PROFILES",
    "CODEX_PARENT_THREAD_ID_HEADER",
    "CODEX_RESPONSES_LITE_HEADER",
    "CODEX_SESSION_ID_HEADER",
    "CODEX_SESSION_ID_KEY",
    "CODEX_SUBAGENT_HEADER",
    "CODEX_THREAD_ID_HEADER",
    "CODEX_THREAD_ID_KEY",
    "CODEX_TURN_ID_KEY",
    "CODEX_TURN_METADATA_KEY",
    "CODEX_TURN_STATE_HEADER",
    "CODEX_WINDOW_ID_KEY",
    "CodexModelProfile",
    "codex_client_metadata",
    "codex_compatibility_headers",
    "codex_model_profile",
    "codex_session_headers",
    "lite_item_id",
    "load_or_create_installation_id",
    "responses_lite_tools",
]
