"""Descriptive operating-system process titles for long-lived FCC workers."""

import contextlib
import re

import setproctitle

from free_claude_code.core.branding import PRODUCT_NAME

_TITLE_PREFIX = PRODUCT_NAME
_MAX_TITLE_LENGTH = 80
_INVALID_TITLE_CHARACTERS = re.compile(r"[^A-Za-z0-9._ -]+")


def build_process_title(component: str, detail: str | None = None) -> str:
    """Build a bounded, non-sensitive title for local process viewers."""

    clean_component = _clean_component(component) or "process"
    title = f"{_TITLE_PREFIX} {clean_component}"
    clean_detail = _clean_component(detail or "")
    if clean_detail:
        title = f"{title} [{clean_detail}]"
    return title[:_MAX_TITLE_LENGTH].rstrip()


def set_process_identity(component: str, detail: str | None = None) -> str:
    """Set and return the descriptive title visible in Activity Monitor.

    Process labels are operational metadata only. Setting a title must never
    prevent the actual FCC command from starting, so platform/runtime errors
    from the native extension are deliberately ignored.
    """

    title = build_process_title(component, detail)
    with contextlib.suppress(OSError, RuntimeError, ValueError):
        setproctitle.setproctitle(title)
    return title


def _clean_component(value: str) -> str:
    compact = " ".join(value.split())
    return _INVALID_TITLE_CHARACTERS.sub("-", compact).strip(" -")


__all__ = ["build_process_title", "set_process_identity"]
