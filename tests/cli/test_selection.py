"""Tests for the shared terminal selection primitive."""

from types import SimpleNamespace

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
