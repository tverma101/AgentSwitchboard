"""Small reusable terminal selection primitive for local control surfaces."""

import curses
import sys
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SelectionItem:
    """One stable item shown by the line-oriented or curses picker."""

    item_id: str
    label: str
    detail: str = ""
    last_used: float = 0.0


def fuzzy_match(items: Sequence[SelectionItem], query: str) -> list[SelectionItem]:
    """Return deterministic subsequence matches ranked by match tightness."""

    unique_items: list[SelectionItem] = []
    seen_ids: set[str] = set()
    for item in items:
        if item.item_id in seen_ids:
            continue
        seen_ids.add(item.item_id)
        unique_items.append(item)

    normalized = query.casefold().strip()
    if not normalized:
        return sorted(
            unique_items,
            key=lambda item: (-item.last_used, item.label.casefold(), item.item_id),
        )

    scored: list[tuple[int, SelectionItem]] = []
    for item in unique_items:
        haystack = f"{item.label} {item.detail} {item.item_id}".casefold()
        score = _subsequence_score(haystack, normalized)
        if score is not None:
            scored.append((score, item))
    scored.sort(
        key=lambda pair: (
            pair[0],
            -pair[1].last_used,
            pair[1].label.casefold(),
            pair[1].item_id,
        )
    )
    return [item for _, item in scored]


def _subsequence_score(haystack: str, needle: str) -> int | None:
    position = -1
    score = 0
    for character in needle:
        next_position = haystack.find(character, position + 1)
        if next_position < 0:
            return None
        score += next_position - position - 1
        position = next_position
    return score


def choose_item(
    items: Sequence[SelectionItem],
    *,
    title: str,
    initial_query: str = "",
    default_item_id: str | None = None,
    footer: str = "type filter · ↑↓ move · enter select · esc cancel",
) -> SelectionItem | None:
    """Select one item without adding a TUI dependency."""

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        matches = fuzzy_match(items, initial_query)
        if default_item_id is not None:
            default = next(
                (item for item in matches if item.item_id == default_item_id), None
            )
            if default is not None:
                return default
        return matches[0] if matches else None
    return curses.wrapper(
        _picker,
        tuple(items),
        title,
        initial_query,
        default_item_id,
        footer,
    )


def _picker(
    screen: curses.window,
    items: tuple[SelectionItem, ...],
    title: str,
    initial_query: str,
    default_item_id: str | None,
    footer: str,
) -> SelectionItem | None:
    curses.curs_set(0)
    screen.keypad(True)
    query = initial_query
    initial_matches = fuzzy_match(items, initial_query)
    selected = next(
        (
            index
            for index, item in enumerate(initial_matches)
            if item.item_id == default_item_id
        ),
        0,
    )

    while True:
        matches = fuzzy_match(items, query)
        selected = min(selected, max(0, len(matches) - 1))
        screen.erase()
        height, width = screen.getmaxyx()
        max_width = max(1, width - 1)
        screen.addnstr(0, 0, title, max_width)
        if height > 1:
            screen.addnstr(1, 0, f"> {query}", max_width)

        visible_rows = max(0, height - 4)
        for row, item in enumerate(matches[:visible_rows]):
            prefix = ">" if row == selected else " "
            marker = "*" if item.item_id == default_item_id else " "
            detail = f" {item.detail}" if item.detail else ""
            text = f"{prefix}{marker} {item.label}{detail}"
            screen.addnstr(row + 2, 0, text, max_width)

        if height > 0:
            screen.addnstr(height - 1, 0, footer, max_width)
        screen.refresh()

        key = screen.get_wch()
        if key in ("\x1b", "\x03"):
            return None
        if key in ("\n", "\r", curses.KEY_ENTER):
            return matches[selected] if matches else None
        if key == curses.KEY_UP:
            selected = max(0, selected - 1)
            continue
        if key == curses.KEY_DOWN:
            selected = min(max(0, len(matches) - 1), selected + 1)
            continue
        if key in (curses.KEY_BACKSPACE, "\b", "\x7f"):
            query = query[:-1]
            selected = 0
            continue
        if isinstance(key, str) and key.isprintable():
            query += key
            selected = 0
