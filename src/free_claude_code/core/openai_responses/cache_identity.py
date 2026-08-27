"""Conservative metadata-only identity selection for Responses caching."""

import re
from collections.abc import Iterable, Mapping
from typing import Any

_MAX_CACHE_KEY_LENGTH = 256
_SAFE_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}")
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"(?:[0-9]{4}[-_][0-9]{2}[-_][0-9]{2}|[0-9]{8,14})"
    r"(?:[Tt _-][0-9]{2}(?::[0-9]{2}){0,2}(?:[.:][0-9]+)?(?:Z|[+-][0-9]{2}:?[0-9]{2})?)?"
)
_VOLATILE_PREFIX_RE = re.compile(
    r"(?:req(?:uest)?|turn|trace|run|event|attempt|response|message|msg|call|time|timestamp)[_-]",
    re.IGNORECASE,
)
_SECRET_PREFIX_RE = re.compile(
    r"(?:sk|pk|rk|api[_-]?key|token|secret|bearer|ghp|github_pat|AIza|eyJ)(?:[-_:]|$)",
    re.IGNORECASE,
)
_SECRET_WORD_RE = re.compile(
    r"(?:secret|password|api[_-]?key|authorization|bearer)",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")


def select_prompt_cache_key(
    *,
    explicit: object,
    session: object,
    metadata: Mapping[str, Any] | None,
    content_values: Iterable[str] = (),
) -> str | None:
    """Select one stable opaque identifier without deriving it from content.

    The request body may carry an explicit Responses ``prompt_cache_key`` or a
    client session header.  ``metadata.session_id`` and ``metadata.user_id``
    are compatibility fallbacks only.  Content values are supplied solely to
    reject an identifier that is itself copied from the request; they are never
    used to derive a key.

    A session header is allowed to be a UUID because Claude clients commonly
    use opaque UUID session identities.  Explicit keys and metadata fallbacks
    reject bare UUIDs, which prevents a per-turn request UUID from becoming a
    cache partition.
    """

    content_snapshot = tuple(content_values)
    candidates = (
        ("explicit", explicit),
        ("session", session),
        ("metadata.session_id", _metadata_value(metadata, "session_id")),
        ("metadata.user_id", _metadata_value(metadata, "user_id")),
    )
    for source, candidate in candidates:
        normalized = _safe_identifier(
            candidate,
            source=source,
            content_values=content_snapshot,
        )
        if normalized is not None:
            return normalized
    return None


def _metadata_value(metadata: Mapping[str, Any] | None, key: str) -> object:
    if metadata is None:
        return None
    return metadata.get(key)


def _safe_identifier(
    candidate: object,
    *,
    source: str,
    content_values: tuple[str, ...],
) -> str | None:
    if not isinstance(candidate, str):
        return None
    normalized = candidate.strip()
    if (
        not normalized
        or len(normalized) > _MAX_CACHE_KEY_LENGTH
        or _SAFE_IDENTIFIER_RE.fullmatch(normalized) is None
    ):
        return None

    lowered = normalized.casefold()
    if (
        _URL_RE.search(normalized)
        or _DATE_RE.fullmatch(normalized) is not None
        or _VOLATILE_PREFIX_RE.match(normalized) is not None
        or _SECRET_PREFIX_RE.match(normalized) is not None
        or _SECRET_WORD_RE.search(normalized) is not None
        or (source != "session" and _UUID_RE.fullmatch(normalized) is not None)
        or _matches_content(normalized, content_values)
        or lowered in {"anonymous", "default", "none", "null", "unknown"}
    ):
        return None
    return normalized


def _matches_content(candidate: str, content_values: tuple[str, ...]) -> bool:
    folded_candidate = candidate.casefold()
    for value in content_values:
        if not isinstance(value, str):
            continue
        folded_value = value.strip().casefold()
        if not folded_value:
            continue
        if folded_candidate == folded_value:
            return True
        if len(folded_candidate) >= 4 and folded_candidate in folded_value:
            return True
    return False
