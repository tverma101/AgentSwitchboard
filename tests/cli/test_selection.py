"""Tests for the shared terminal selection primitive."""

import curses
from types import SimpleNamespace
from typing import cast

import free_claude_code.cli.selection as selection
from free_claude_code.cli.selection import SelectionItem, choose_item, fuzzy_match


def test_fuzzy_match_keeps_stable_ids_and_orders_recent_ties() -> None:
    items = [
        SelectionItem("two-id", "Two", "same", last_used=2.0),
        SelectionItem("one-id", "One", "same", last_used=1.0),
    ]

    matches = fuzzy_match(items, "same")

    assert [item.item_id for item in matches] == ["two-id", "one-id"]


def test_non_tty_picker_returns_first_fuzzy_match(monkeypatch) -> None:
    non_tty = SimpleNamespace(isatty=lambda: False)
    monkeypatch.setattr(selection.sys, "stdin", non_tty)
    monkeypatch.setattr(selection.sys, "stdout", non_tty)
    items = [
        SelectionItem("other", "Other"),
        SelectionItem("wanted", "Wanted"),
    ]

    assert choose_item(items, title="Items", initial_query="want") == items[1]


def test_fuzzy_match_deduplicates_stable_item_ids() -> None:
    items = [
        SelectionItem("repo", "Repo", "first"),
        SelectionItem("repo", "Repo", "duplicate"),
        SelectionItem("other", "Other"),
    ]

    assert [item.item_id for item in fuzzy_match(items, "")] == ["other", "repo"]


def test_non_tty_picker_returns_selected_default_when_available(monkeypatch) -> None:
    non_tty = SimpleNamespace(isatty=lambda: False)
    monkeypatch.setattr(selection.sys, "stdin", non_tty)
    monkeypatch.setattr(selection.sys, "stdout", non_tty)
    items = [
        SelectionItem("first", "First"),
        SelectionItem("default", "Default"),
    ]

    assert choose_item(items, title="Items", default_item_id="default") == items[1]


def test_picker_fails_closed_when_terminal_stream_probe_raises(monkeypatch) -> None:
    class BrokenStream:
        def isatty(self) -> bool:
            raise RuntimeError("stream probe failed")

    monkeypatch.setattr(selection.sys, "stdin", BrokenStream())
    monkeypatch.setattr(selection.sys, "stdout", BrokenStream())

    items = [SelectionItem("one", "One"), SelectionItem("two", "Two")]

    assert choose_item(items, title="Items") == items[0]


def test_curses_picker_marks_default_item(monkeypatch) -> None:
    class FakeScreen:
        def __init__(self) -> None:
            self.lines: list[str] = []

        def keypad(self, _enabled: bool) -> None:
            pass

        def erase(self) -> None:
            self.lines.clear()

        def getmaxyx(self) -> tuple[int, int]:
            return 10, 80

        def addnstr(self, _row: int, _column: int, text: str, _width: int) -> None:
            self.lines.append(text)

        def refresh(self) -> None:
            pass

        def get_wch(self) -> str:
            return "\x1b"

    fake_screen = FakeScreen()
    screen = cast(curses.window, fake_screen)
    monkeypatch.setattr(selection.curses, "curs_set", lambda _value: None)

    assert (
        selection._picker(
            screen,
            (
                SelectionItem("first", "First"),
                SelectionItem("default", "Default"),
            ),
            "Items",
            "",
            "default",
            "footer",
        )
        is None
    )
    assert any("* Default" in line for line in fake_screen.lines)


def test_curses_picker_scrolls_to_selected_row() -> None:
    class FakeScreen:
        def __init__(self) -> None:
            self.rendered: list[list[str]] = []
            self.lines: list[str] = []
            self.keys = [curses.KEY_DOWN] * 5 + ["\n"]

        def keypad(self, _enabled: bool) -> None:
            pass

        def erase(self) -> None:
            self.lines = []

        def getmaxyx(self) -> tuple[int, int]:
            return 6, 80

        def addnstr(self, _row: int, _column: int, text: str, _width: int) -> None:
            self.lines.append(text)

        def refresh(self) -> None:
            self.rendered.append(list(self.lines))

        def get_wch(self) -> object:
            return self.keys.pop(0)

    screen = FakeScreen()
    items = tuple(SelectionItem(str(index), f"Item {index}") for index in range(8))

    selected = selection._picker(
        cast(curses.window, screen),
        items,
        "Items",
        "",
        None,
        "footer",
    )

    assert selected == items[5]
    assert any(any("Item 5" in line for line in frame) for frame in screen.rendered)


def test_curses_picker_tolerates_cursor_visibility_failure(
    monkeypatch,
) -> None:
    class FakeScreen:
        def keypad(self, _enabled: bool) -> None:
            pass

        def erase(self) -> None:
            pass

        def getmaxyx(self) -> tuple[int, int]:
            return 4, 40

        def addnstr(self, *_args: object) -> None:
            pass

        def refresh(self) -> None:
            pass

        def get_wch(self) -> str:
            return "\x1b"

    def fail_cursor(_value: int) -> None:
        raise curses.error("cursor unavailable")

    monkeypatch.setattr(selection.curses, "curs_set", fail_cursor)

    assert (
        selection._picker(
            cast(curses.window, FakeScreen()),
            (SelectionItem("one", "One"),),
            "Items",
            "",
            None,
            "footer",
        )
        is None
    )


def test_safe_addnstr_tolerates_resized_terminal_error() -> None:
    class BrokenScreen:
        def addnstr(self, *_args: object) -> None:
            raise curses.error("terminal resized")

    selection._safe_addnstr(cast(curses.window, BrokenScreen()), 0, 0, "text", 1)


def test_curses_picker_handles_resize_before_cancel() -> None:
    class FakeScreen:
        def __init__(self) -> None:
            self.keys = [curses.KEY_RESIZE, "\x1b"]

        def keypad(self, _enabled: bool) -> None:
            pass

        def erase(self) -> None:
            pass

        def getmaxyx(self) -> tuple[int, int]:
            return 3, 20

        def addnstr(self, *_args: object) -> None:
            pass

        def refresh(self) -> None:
            pass

        def get_wch(self) -> object:
            return self.keys.pop(0)

    assert (
        selection._picker(
            cast(curses.window, FakeScreen()),
            (SelectionItem("one", "One"),),
            "Items",
            "",
            None,
            "footer",
        )
        is None
    )
