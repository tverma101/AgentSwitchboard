"""Streaming parser for provider-emitted thinking tags."""

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum


class ContentType(Enum):
    """Type of content chunk."""

    TEXT = "text"
    THINKING = "thinking"


@dataclass
class ContentChunk:
    """A chunk of parsed content."""

    type: ContentType
    content: str


class ThinkTagParser:
    """
    Streaming parser for provider thinking tags.

    Handles ``<think>...</think>`` and ``<summary>...</summary>`` pairs.
    Some thinking models wrap reasoning in ``<summary>`` tags; without
    stripping, an orphan ``</summary>`` leaks into visible answer text even
    though FCC never emits such tags itself. Both pairs map to the thinking
    channel. Handles partial tags at chunk boundaries by buffering.
    """

    OPEN_TAG = "<think>"
    CLOSE_TAG = "</think>"
    SUMMARY_OPEN_TAG = "<summary>"
    SUMMARY_CLOSE_TAG = "</summary>"
    _OPEN_TAGS = (OPEN_TAG, SUMMARY_OPEN_TAG)
    _CLOSE_TAGS = (CLOSE_TAG, SUMMARY_CLOSE_TAG)

    def __init__(self):
        self._buffer: str = ""
        self._in_think_tag: bool = False

    @property
    def in_think_mode(self) -> bool:
        """Whether currently inside a think tag."""
        return self._in_think_tag

    def feed(self, content: str) -> Iterator[ContentChunk]:
        """Feed content and yield parsed chunks."""
        self._buffer += content

        while self._buffer:
            prev_len = len(self._buffer)
            if not self._in_think_tag:
                chunk = self._parse_outside_think()
            else:
                chunk = self._parse_inside_think()

            if chunk:
                yield chunk
            elif len(self._buffer) == prev_len:
                break

    def _parse_outside_think(self) -> ContentChunk | None:
        """Parse content outside think tags."""
        think_start, open_tag = self._find_first(self._buffer, self._OPEN_TAGS)
        orphan_close, close_tag = self._find_first(self._buffer, self._CLOSE_TAGS)

        if orphan_close != -1 and (think_start == -1 or orphan_close < think_start):
            pre_orphan = self._buffer[:orphan_close]
            self._buffer = self._buffer[orphan_close + len(close_tag) :]
            if pre_orphan:
                return ContentChunk(ContentType.TEXT, pre_orphan)
            return None

        if think_start == -1:
            last_bracket = self._buffer.rfind("<")
            if last_bracket != -1:
                potential_tag = self._buffer[last_bracket:]
                if any(
                    len(potential_tag) < len(tag) and tag.startswith(potential_tag)
                    for tag in (*self._OPEN_TAGS, *self._CLOSE_TAGS)
                ):
                    emit = self._buffer[:last_bracket]
                    self._buffer = self._buffer[last_bracket:]
                    if emit:
                        return ContentChunk(ContentType.TEXT, emit)
                    return None

            emit = self._buffer
            self._buffer = ""
            if emit:
                return ContentChunk(ContentType.TEXT, emit)
            return None

        pre_think = self._buffer[:think_start]
        self._buffer = self._buffer[think_start + len(open_tag) :]
        self._in_think_tag = True
        if pre_think:
            return ContentChunk(ContentType.TEXT, pre_think)
        return None

    def _parse_inside_think(self) -> ContentChunk | None:
        """Parse content inside think tags."""
        think_end, close_tag = self._find_first(self._buffer, self._CLOSE_TAGS)

        if think_end == -1:
            longest_close = max(len(tag) for tag in self._CLOSE_TAGS)
            last_bracket = self._buffer.rfind("<")
            if last_bracket != -1 and len(self._buffer) - last_bracket < longest_close:
                potential_tag = self._buffer[last_bracket:]
                if any(tag.startswith(potential_tag) for tag in self._CLOSE_TAGS):
                    emit = self._buffer[:last_bracket]
                    self._buffer = self._buffer[last_bracket:]
                    if emit:
                        return ContentChunk(ContentType.THINKING, emit)
                    return None

            emit = self._buffer
            self._buffer = ""
            if emit:
                return ContentChunk(ContentType.THINKING, emit)
            return None

        thinking_content = self._buffer[:think_end]
        self._buffer = self._buffer[think_end + len(close_tag) :]
        self._in_think_tag = False
        if thinking_content:
            return ContentChunk(ContentType.THINKING, thinking_content)
        return None

    @staticmethod
    def _find_first(buffer: str, tags: tuple[str, ...]) -> tuple[int, str]:
        """Return the earliest tag occurrence and the matched tag."""

        earliest = -1
        matched = ""
        for tag in tags:
            index = buffer.find(tag)
            if index != -1 and (earliest == -1 or index < earliest):
                earliest = index
                matched = tag
        return earliest, matched

    def flush(self) -> ContentChunk | None:
        """Flush any remaining buffered content."""
        if self._buffer:
            chunk_type = (
                ContentType.THINKING if self._in_think_tag else ContentType.TEXT
            )
            content = self._buffer
            self._buffer = ""
            return ContentChunk(chunk_type, content)
        return None
