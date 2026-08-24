"""Bounded, local-only retrieval for context-governor artifacts."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MIN_SLICE_BYTES = 512
MAX_SLICE_BYTES = 1_000_000
MAX_SLICE_LINES = 10_000


class ContextArtifactError(ValueError):
    """A context artifact cannot be read safely under the requested policy."""


@dataclass(frozen=True, slots=True)
class ContextArtifactSlice:
    """A bounded text slice plus metadata for the full local artifact."""

    path: str
    sha256: str
    total_bytes: int
    total_lines: int
    start_line: int
    line_count: int
    end_line: int
    returned_bytes: int
    content: str
    has_more_before: bool
    has_more_after: bool

    def as_response(self) -> dict[str, object]:
        """Return a terminal-friendly response containing only the slice."""

        return {
            "path": self.path,
            "sha256": self.sha256,
            "total_bytes": self.total_bytes,
            "total_lines": self.total_lines,
            "start_line": self.start_line,
            "line_count": self.line_count,
            "end_line": self.end_line,
            "returned_bytes": self.returned_bytes,
            "has_more_before": self.has_more_before,
            "has_more_after": self.has_more_after,
            "content": self.content,
        }


def read_context_artifact_slice(
    path: str | Path,
    *,
    root: str | Path,
    start_line: int = 1,
    line_count: int = 80,
    max_bytes: int = 16 * 1024,
) -> ContextArtifactSlice:
    """Read a bounded UTF-8 slice from an FCC-owned artifact.

    The resolved file must remain below the configured artifact root. The full
    file is hashed and line-counted for integrity metadata, while only the
    requested bounded slice is returned to the caller.
    """

    if start_line < 1:
        raise ContextArtifactError("start_line must be at least 1")
    if not 1 <= line_count <= MAX_SLICE_LINES:
        raise ContextArtifactError(
            f"line_count must be between 1 and {MAX_SLICE_LINES}"
        )
    if not MIN_SLICE_BYTES <= max_bytes <= MAX_SLICE_BYTES:
        raise ContextArtifactError(
            f"max_bytes must be between {MIN_SLICE_BYTES} and {MAX_SLICE_BYTES}"
        )

    root_path = _resolve_directory(root)
    target = _resolve_file(path)
    try:
        target.relative_to(root_path)
    except ValueError as exc:
        raise ContextArtifactError(
            "context artifact path must remain inside FCC's configured artifact directory"
        ) from exc

    try:
        file_size = target.stat().st_size
    except OSError as exc:
        raise ContextArtifactError("context artifact metadata is unavailable") from exc
    if file_size > MAX_ARTIFACT_BYTES:
        raise ContextArtifactError(
            "context artifact exceeds FCC's safe artifact size; retrieve it in "
            "smaller bounded slices from the producing tool"
        )

    digest, total_bytes, total_lines = _file_metadata(target)
    content, end_line = _read_lines(
        target,
        start_line=start_line,
        line_count=line_count,
        max_bytes=max_bytes,
    )
    returned_bytes = len(content.encode("utf-8"))
    return ContextArtifactSlice(
        path=str(target),
        sha256=digest,
        total_bytes=total_bytes,
        total_lines=total_lines,
        start_line=start_line,
        line_count=max(0, end_line - start_line + 1),
        end_line=end_line,
        returned_bytes=returned_bytes,
        content=content,
        has_more_before=start_line > 1,
        has_more_after=end_line < total_lines,
    )


def _resolve_directory(value: str | Path) -> Path:
    path = Path(value).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ContextArtifactError("context artifact directory is unavailable") from exc
    if not resolved.is_dir():
        raise ContextArtifactError("context artifact root is not a directory")
    return resolved


def _resolve_file(value: str | Path) -> Path:
    path = Path(value).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ContextArtifactError("context artifact file is unavailable") from exc
    if not resolved.is_file():
        raise ContextArtifactError("context artifact path is not a regular file")
    return resolved


def _file_metadata(path: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    total_bytes = 0
    newline_count = 0
    last_byte = b""
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(64 * 1024):
                digest.update(chunk)
                total_bytes += len(chunk)
                newline_count += chunk.count(b"\n")
                last_byte = chunk[-1:]
    except OSError as exc:
        raise ContextArtifactError("context artifact could not be read") from exc
    total_lines = newline_count + (1 if total_bytes and last_byte != b"\n" else 0)
    return digest.hexdigest(), total_bytes, total_lines


def _read_lines(
    path: Path,
    *,
    start_line: int,
    line_count: int,
    max_bytes: int,
) -> tuple[str, int]:
    end_target = start_line + line_count - 1
    collected: list[bytes] = []
    returned_bytes = 0
    end_line = start_line - 1
    try:
        with path.open("rb") as handle:
            for number, raw_line in enumerate(handle, start=1):
                if number < start_line:
                    continue
                if number > end_target:
                    break
                remaining = max_bytes - returned_bytes
                if remaining <= 0:
                    break
                selected = raw_line[:remaining]
                collected.append(selected)
                returned_bytes += len(selected)
                end_line = number
                if len(selected) < len(raw_line) or returned_bytes >= max_bytes:
                    break
    except OSError as exc:
        raise ContextArtifactError("context artifact slice could not be read") from exc
    return b"".join(collected).decode("utf-8", errors="replace"), end_line
