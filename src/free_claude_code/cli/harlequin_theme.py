"""Harlequin Textual theme, vendored from upstream MIT code.

Source: tconbeer/harlequin
Commit: fcfaa6c524a6cd47e17701d931eac0243c8c85b6
Copyright (c) 2023 Ted Conbeer
See THIRD_PARTY_NOTICES.md.
"""

from textual.theme import Theme

GREEN = "#45FFCA"
YELLOW = "#FEFFAC"
PINK = "#FFB6D9"
PURPLE = "#D67BFF"
GRAY = "#777777"
DARK_GRAY = "#555555"
BLACK = "#0C0C0C"
WHITE = "#DDDDDD"

HARLEQUIN_TEXTUAL_THEME = Theme(
    name="harlequin",
    primary=YELLOW,
    secondary=GREEN,
    warning=YELLOW,
    error=PINK,
    success=GREEN,
    accent=PINK,
    foreground=WHITE,
    background=BLACK,
    surface=BLACK,
    panel=DARK_GRAY,
    dark=True,
)
