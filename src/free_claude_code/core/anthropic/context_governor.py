"""Provider-independent context-pressure governance for tool results."""

import hashlib
import json
import os
import stat
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from free_claude_code.core.diagnostics import redact_sensitive_error_text

from .content import (
    get_block_attr,
    get_block_type,
    normalize_tool_result_content,
)
from .models import Message, MessagesRequest

DEFAULT_TOOL_RESULT_MAX_BYTES = 16 * 1024
MAX_TOOL_RESULT_MAX_BYTES = 1_000_000
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_OPEN_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class ContextGovernanceError(ValueError):
    """A tool result cannot be safely reduced under the active policy."""


@dataclass(frozen=True, slots=True)
class ContextGovernorConfig:
    """Runtime policy for reducing model-visible tool-result payloads."""

    enabled: bool = True
    tool_result_max_bytes: int = DEFAULT_TOOL_RESULT_MAX_BYTES
    # Media is protocol-significant input. Preserve it unless a caller
    # explicitly opts into strict oversized-media rejection.
    preserve_media: bool = True
    artifact_dir: Path = field(
        default_factory=lambda: Path.home() / ".fcc" / "context-artifacts"
    )

    def __post_init__(self) -> None:
        if not 512 <= self.tool_result_max_bytes <= MAX_TOOL_RESULT_MAX_BYTES:
            raise ValueError(
                "tool_result_max_bytes must be between 512 and "
                f"{MAX_TOOL_RESULT_MAX_BYTES}"
            )


@dataclass(frozen=True, slots=True)
class ContextGovernanceRecord:
    """Metadata-only evidence for one redirected tool result."""

    tool_use_id: str
    original_bytes: int
    visible_bytes: int
    original_tokens: int
    visible_tokens: int
    original_lines: int
    visible_lines: int
    reduction_ratio: float
    artifact_path: str
    artifact_sha256: str
    pressure_mode: str = "tool_result_redirected"
    semantic_verification: str = "text_only"

    def as_trace_fields(self) -> dict[str, object]:
        """Return receipt fields without including result content."""

        return {
            "tool_use_id": self.tool_use_id,
            "original_bytes": self.original_bytes,
            "visible_bytes": self.visible_bytes,
            "original_tokens": self.original_tokens,
            "visible_tokens": self.visible_tokens,
            "original_lines": self.original_lines,
            "visible_lines": self.visible_lines,
            "reduction_ratio": self.reduction_ratio,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "pressure_mode": self.pressure_mode,
            "semantic_verification": self.semantic_verification,
        }


@dataclass(frozen=True, slots=True)
class GovernedMessagesRequest:
    """A request after safe context governance and its receipt records."""

    request: MessagesRequest
    records: tuple[ContextGovernanceRecord, ...] = ()


def govern_messages_request(
    request: MessagesRequest,
    config: ContextGovernorConfig,
) -> GovernedMessagesRequest:
    """Bound text-only tool results without changing exact-state content.

    FCC can only govern a tool result once the client sends it back to the
    gateway. Text-only results can be redirected to a local artifact. Images,
    thinking/signature state, and structured JSON are never truncated. When
    ``preserve_media`` is enabled by the application route, media-containing
    results pass through unchanged so a vision model receives the original
    image rather than a lossy excerpt. Other oversized structured values are
    rejected explicitly so protocol state cannot be silently corrupted.
    """

    if not config.enabled:
        return GovernedMessagesRequest(request)

    changed = False
    records: list[ContextGovernanceRecord] = []
    messages: list[Message] = []
    for message in request.messages:
        if not isinstance(message.content, list):
            messages.append(message)
            continue

        blocks: list[Any] = []
        message_changed = False
        for block in message.content:
            if get_block_type(block) != "tool_result":
                blocks.append(block)
                continue

            original_content = get_block_attr(block, "content", "")
            content = normalize_tool_result_content(original_content)
            if content is not original_content:
                block = _copy_block_with_content(block, content)
                message_changed = True
            text = _text_only_content(content)
            if text is None:
                if config.preserve_media and _contains_media_content(content):
                    blocks.append(block)
                    continue
                if _serialized_size(content) > config.tool_result_max_bytes:
                    tool_use_id = str(get_block_attr(block, "tool_use_id", "unknown"))
                    raise ContextGovernanceError(
                        "tool result for "
                        f"{tool_use_id!r} exceeds the context-governor limit, "
                        "but contains structured or media state that FCC will "
                        "not truncate; retrieve a bounded text slice or disable "
                        "the governor explicitly"
                    )
                blocks.append(block)
                continue

            original_bytes = len(text.encode("utf-8"))
            if original_bytes <= config.tool_result_max_bytes:
                blocks.append(block)
                continue

            artifact_text = redact_sensitive_error_text(text)
            artifact_path, artifact_sha256 = _write_artifact(
                artifact_text,
                artifact_dir=config.artifact_dir,
            )
            replacement = _redirected_text(
                artifact_text,
                original_bytes=original_bytes,
                original_tokens=_estimated_tokens(text),
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
                max_bytes=config.tool_result_max_bytes,
            )
            visible_bytes = len(replacement.encode("utf-8"))
            records.append(
                ContextGovernanceRecord(
                    tool_use_id=str(get_block_attr(block, "tool_use_id", "unknown")),
                    original_bytes=original_bytes,
                    visible_bytes=visible_bytes,
                    original_tokens=_estimated_tokens(text),
                    visible_tokens=_estimated_tokens(replacement),
                    original_lines=_estimated_lines(text),
                    visible_lines=_estimated_lines(replacement),
                    reduction_ratio=round(
                        1 - (visible_bytes / max(1, original_bytes)),
                        6,
                    ),
                    artifact_path=artifact_path,
                    artifact_sha256=artifact_sha256,
                )
            )
            blocks.append(_copy_block_with_content(block, replacement))
            message_changed = True

        if message_changed:
            changed = True
            messages.append(message.model_copy(update={"content": blocks}))
        else:
            messages.append(message)

    if not changed:
        return GovernedMessagesRequest(request)
    return GovernedMessagesRequest(
        request=request.model_copy(update={"messages": messages}),
        records=tuple(records),
    )


def _text_only_content(content: object) -> str | None:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if get_block_type(block) != "text":
            return None
        text = get_block_attr(block, "text")
        if not isinstance(text, str):
            return None
        parts.append(text)
    return "".join(parts)


_MEDIA_BLOCK_TYPES = frozenset({"audio", "document", "image", "video"})


def _contains_media_content(value: object) -> bool:
    """Return whether a value contains a protocol media block."""

    if get_block_type(value) in _MEDIA_BLOCK_TYPES:
        return True
    if isinstance(value, dict):
        return any(_contains_media_content(child) for child in value.values())
    if isinstance(value, list | tuple):
        return any(_contains_media_content(child) for child in value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="python")
        if isinstance(dumped, dict):
            return _contains_media_content(dumped)
    return False


def _serialized_size(value: object) -> int:
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    try:
        encoded = json.dumps(
            value,
            default=_json_default,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except TypeError, ValueError, OverflowError:
        encoded = str(value).encode("utf-8", errors="replace")
    return len(encoded)


def _json_default(value: object) -> object:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return str(value)


def _write_artifact(text: str, *, artifact_dir: Path) -> tuple[str, str]:
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_ARTIFACT_BYTES:
        raise ContextGovernanceError(
            "tool result exceeds FCC's safe artifact limit; retrieve it in "
            "smaller bounded slices before retrying"
        )
    digest = hashlib.sha256(encoded).hexdigest()
    directory = artifact_dir.expanduser()
    try:
        directory = directory.resolve()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if stat.S_IMODE(directory.stat().st_mode) & 0o077:
            raise ContextGovernanceError(
                "FCC context artifact directory must not be group or world accessible"
            )
        path = directory / f"tool-result-{digest[:24]}.txt"
        try:
            fd = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN_NOFOLLOW,
                0o600,
            )
        except FileExistsError:
            if _existing_artifact_matches(path, digest=digest, size=len(encoded)):
                return str(path), digest
            raise ContextGovernanceError(
                "FCC context artifact path already exists with different content"
            ) from None
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
        except OSError:
            with suppress(OSError):
                path.unlink()
            raise
    except ContextGovernanceError:
        raise
    except (OSError, RuntimeError) as exc:
        raise ContextGovernanceError(
            "FCC could not create the local context artifact; refusing to "
            "truncate the tool result"
        ) from exc
    return str(path), digest


def _existing_artifact_matches(path: Path, *, digest: str, size: int) -> bool:
    """Accept an existing artifact only when it is private and byte-identical."""

    try:
        fd = os.open(path, os.O_RDONLY | _OPEN_NOFOLLOW)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode):
                return False
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise ContextGovernanceError(
                    "FCC context artifact already exists with non-private permissions"
                )
            if metadata.st_size != size:
                return False
            actual = hashlib.sha256()
            while chunk := os.read(fd, 64 * 1024):
                actual.update(chunk)
        finally:
            os.close(fd)
    except ContextGovernanceError:
        raise
    except OSError as exc:
        raise ContextGovernanceError(
            "FCC could not verify the existing local context artifact"
        ) from exc
    return actual.hexdigest() == digest


def _redirected_text(
    text: str,
    *,
    original_bytes: int,
    original_tokens: int,
    artifact_path: str,
    artifact_sha256: str,
    max_bytes: int,
) -> str:
    """Build a bounded, explicit locator preserving head and tail context."""

    header = (
        "[FCC context governor: tool result redirected]\n"
        f"original_bytes={original_bytes} visible_bytes=0000000000 "
        f"original_tokens={original_tokens} "
        f"artifact_sha256={artifact_sha256} artifact_path={artifact_path}\n"
        "The complete redacted result is outside model context. Retrieve a "
        "bounded slice from artifact_path before relying on omitted content.\n"
        "--- excerpt begin ---\n"
    )
    footer = "\n--- excerpt end ---"
    separator = "\n... omitted middle ...\n"
    available = max_bytes - len(header.encode("utf-8")) - len(footer.encode("utf-8"))
    if available <= len(separator.encode("utf-8")):
        raise ContextGovernanceError(
            "FCC context-governor limit is too small for its explicit artifact locator"
        )

    excerpt_budget = available - len(separator.encode("utf-8"))
    head_budget = excerpt_budget // 2
    tail_budget = excerpt_budget - head_budget
    head = _clip_utf8(text, head_budget, from_end=False)
    tail = _clip_utf8(text, tail_budget, from_end=True)
    replacement = header + head + separator + tail + footer
    visible_bytes = len(replacement.encode("utf-8"))
    return replacement.replace(
        "visible_bytes=0000000000",
        f"visible_bytes={visible_bytes:010d}",
    )


def _clip_utf8(text: str, max_bytes: int, *, from_end: bool) -> str:
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text
    clipped = data[-max_bytes:] if from_end else data[:max_bytes]
    return clipped.decode("utf-8", errors="ignore")


def _copy_block_with_content(block: object, content: Any) -> object:
    model_copy = getattr(block, "model_copy", None)
    if callable(model_copy):
        return model_copy(update={"content": content})
    if isinstance(block, dict):
        return {**block, "content": content}
    raise ContextGovernanceError(
        "FCC encountered an unsupported tool-result block and will not truncate it"
    )


def _estimated_tokens(text: str) -> int:
    return max(1, len(text.encode("utf-8")) // 4)


def _estimated_lines(text: str) -> int:
    """Estimate logical text lines without inventing a trailing empty line."""

    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)
