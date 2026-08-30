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
