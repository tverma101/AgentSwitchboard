"""Harlequin's Textual app-base pattern, vendored under MIT.

Source: tconbeer/harlequin
Commit: fcfaa6c524a6cd47e17701d931eac0243c8c85b6
Copyright (c) 2023 Ted Conbeer
See THIRD_PARTY_NOTICES.md.
"""

from textual.app import App
from textual.binding import ActiveBinding
from textual.screen import Screen

from .harlequin_theme import HARLEQUIN_TEXTUAL_THEME


class ScreenBase(Screen):
    """Harlequin screen ordering: application bindings before widget bindings."""

    @property
    def active_bindings(self) -> dict[str, ActiveBinding]:
        def sort_key(binding_pair: tuple[str, ActiveBinding]) -> int:
            return 0 if binding_pair[1].node == self.app else 1

        return dict(sorted(super().active_bindings.items(), key=sort_key))


class HarlequinAppBase(App, inherit_bindings=False):
    """Small vendored subset of Harlequin's ``AppBase`` for the control shell."""

    def __init__(self) -> None:
        super().__init__()
        self.register_theme(HARLEQUIN_TEXTUAL_THEME)
        self.theme = "harlequin"

    def get_default_screen(self) -> Screen:
        return ScreenBase(id="_default")

    def _handle_exception(self, error: Exception) -> None:
        if self._exit:
            return
        super()._handle_exception(error)
