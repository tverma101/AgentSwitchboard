"""Configuration and namespace helpers for FCC Learning profiles."""

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from free_claude_code.core.profile import (
    DEFAULT_PROFILE,
    PROFILE_ENV,
    PROFILE_SCHEMA,
    PROFILE_VERSION,
    ProfileNameError,
    normalize_profile,
    resolve_profile,
)

LearningProfileError = ProfileNameError

__all__ = [
    "DEFAULT_PROFILE",
    "PROFILE_ENV",
    "PROFILE_SCHEMA",
    "PROFILE_VERSION",
    "LearningProfileError",
    "configured_profile",
    "extract_profile_argument",
    "learning_home",
    "normalize_profile",
    "profile_database",
    "profile_home",
    "qualify_skill_key",
]


def configured_profile(environment: Mapping[str, str] | None = None) -> str:
    """Return the explicit environment-selected profile or the default."""

    return resolve_profile(environment=environment).name


def learning_home() -> Path:
    """Return the root directory containing all FCC Learning profiles."""

    override = os.environ.get("FCC_LEARNING_HOME")
    return (
        Path(override).expanduser() if override else Path.home() / ".fcc" / "learning"
    )


def profile_home(profile: str | None = None) -> Path:
    """Return the isolated state directory for one profile."""

    name = normalize_profile(profile) if profile is not None else configured_profile()
    root = learning_home()
    # Keep the historical default database location readable and writable.
    # Named profiles are always placed below an explicit namespace directory.
    return root if name == DEFAULT_PROFILE else root / "profiles" / name


def profile_database(profile: str | None = None) -> Path:
    """Return the SQLite path for one profile."""

    return profile_home(profile) / "learning.db"


def qualify_skill_key(skill_key: str, profile: str | None = None) -> str:
    """Prefix generated skill keys for non-default profile isolation."""

    name = normalize_profile(profile) if profile is not None else configured_profile()
    if name == DEFAULT_PROFILE:
        return skill_key
    return f"fcc-{name}-{skill_key.removeprefix('fcc-')}"


def extract_profile_argument(
    argv: Sequence[str],
) -> tuple[list[str], str | None]:
    """Remove FCC's launcher-only ``--profile`` option from client arguments."""

    remaining: list[str] = []
    selected: str | None = None
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--":
            remaining.extend(argv[index:])
            break
        if argument == "--profile":
            if index + 1 >= len(argv):
                raise LearningProfileError("--profile requires a profile name")
            value = argv[index + 1]
            index += 2
        elif argument.startswith("--profile="):
            value = argument.split("=", 1)[1]
            index += 1
        else:
            remaining.append(argument)
            index += 1
            continue
        normalized = normalize_profile(value)
        if selected is not None:
            raise LearningProfileError("--profile may be provided only once")
        selected = normalized
    return remaining, selected
