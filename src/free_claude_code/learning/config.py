"""Configuration and namespace helpers for FCC Learning profiles."""

import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

PROFILE_ENV = "FCC_LEARNING_PROFILE"
DEFAULT_PROFILE = "default"
PROFILE_SCHEMA = "fcc.learning.profile"
PROFILE_VERSION = 1

_PROFILE_RE = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,31})\Z")


class LearningProfileError(ValueError):
    """Raised when an explicit learning profile name is unsafe or invalid."""


def normalize_profile(profile: str | None) -> str:
    """Normalize and validate one profile identifier."""

    value = DEFAULT_PROFILE if profile is None else profile.strip().casefold()
    if not _PROFILE_RE.fullmatch(value):
        raise LearningProfileError(
            "learning profile must use 1-32 lowercase letters, digits, '.', '_' or '-'"
        )
    return value


def configured_profile(environment: Mapping[str, str] | None = None) -> str:
    """Return the explicit environment-selected profile or the default."""

    values = os.environ if environment is None else environment
    return normalize_profile(values.get(PROFILE_ENV))


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
