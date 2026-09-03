"""Configuration and namespace helpers for FCC Learning profiles."""

import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

PROFILE_ENV = "FCC_LEARNING_PROFILE"
LEARNING_ENABLED_ENV = "FCC_LEARNING_ENABLED"
DEFAULT_PROFILE = "default"
PROFILE_SCHEMA = "fcc.learning.profile"
PROFILE_VERSION = 1
_PROFILE_ARCHIVE_DIR = ".archive"
_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})

_PROFILE_RE = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,31})\Z")


class LearningProfileError(ValueError):
    """Raised when an explicit learning profile name is unsafe or invalid."""


def learning_enabled(environment: Mapping[str, str] | None = None) -> bool:
    """Return whether FCC Learning was explicitly opted into.

    Learning is intentionally opt-in.  Any value other than a documented
    truthy value, including an unset variable, keeps hooks and post-turn
    distillation disabled.
    """

    values = os.environ if environment is None else environment
    return values.get(LEARNING_ENABLED_ENV, "0").strip().lower() in _ENABLED_VALUES


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
    if override:
        return Path(override).expanduser()
    # Mirrors config.paths.FCC_CONFIG_DIR so sandbox runs stay out of ~/.fcc;
    # learning stays dependency-neutral and must not import the config package.
    config_override = os.environ.get("FCC_CONFIG_DIR", "").strip()
    if config_override:
        return Path(config_override).expanduser() / "learning"
    return Path.home() / ".fcc" / "learning"


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


def list_profiles() -> tuple[str, ...]:
    """Return the default profile and discovered named profile directories."""

    profiles_root = learning_home() / "profiles"
    names = {DEFAULT_PROFILE}
    try:
        entries = profiles_root.iterdir()
    except FileNotFoundError:
        return (DEFAULT_PROFILE,)
    except OSError as exc:
        raise LearningProfileError("cannot list learning profiles") from exc
    for entry in entries:
        if (
            entry.name == _PROFILE_ARCHIVE_DIR
            or entry.name.startswith(".")
            or entry.is_symlink()
            or not entry.is_dir()
        ):
            continue
        try:
            name = normalize_profile(entry.name)
        except LearningProfileError:
            continue
        if name != DEFAULT_PROFILE:
            names.add(name)
    return tuple(sorted(names))


def list_archived_profiles() -> tuple[str, ...]:
    """Return named profiles available in the local recovery archive."""

    archive_root = learning_home() / "profiles" / _PROFILE_ARCHIVE_DIR
    names: set[str] = set()
    try:
        entries = archive_root.iterdir()
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise LearningProfileError("cannot list archived learning profiles") from exc
    for entry in entries:
        if entry.name.startswith(".") or entry.is_symlink() or not entry.is_dir():
            continue
        try:
            name = normalize_profile(entry.name)
        except LearningProfileError:
            continue
        if name != DEFAULT_PROFILE:
            names.add(name)
    return tuple(sorted(names))


def _named_profile_path(profile: str) -> tuple[str, Path]:
    name = normalize_profile(profile)
    if name == DEFAULT_PROFILE:
        raise LearningProfileError("the default profile cannot be renamed or archived")
    return name, learning_home() / "profiles" / name


def _ensure_profile_is_not_active(name: str) -> None:
    if configured_profile() == name:
        raise LearningProfileError(
            f"profile {name!r} is active; start a new session before changing it"
        )


def create_profile(profile: str) -> str:
    """Create an empty named profile without initializing a learning database."""

    name, path = _named_profile_path(profile)
    if path.exists() or path.is_symlink():
        raise LearningProfileError(f"profile already exists: {name}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir()
    except FileExistsError as exc:
        raise LearningProfileError(f"profile already exists: {name}") from exc
    except OSError as exc:
        raise LearningProfileError(f"cannot create profile: {name}") from exc
    return name


def rename_profile(profile: str, new_profile: str) -> str:
    """Atomically rename one inactive named profile without deleting its state."""

    name, source = _named_profile_path(profile)
    target_name, target = _named_profile_path(new_profile)
    if name == target_name:
        raise LearningProfileError("new profile name must differ from the old name")
    _ensure_profile_is_not_active(name)
    if source.is_symlink() or not source.is_dir():
        raise LearningProfileError(f"profile does not exist: {name}")
    if target.exists() or target.is_symlink():
        raise LearningProfileError(f"profile already exists: {target_name}")
    try:
        source.rename(target)
    except OSError as exc:
        raise LearningProfileError(
            f"cannot rename profile {name!r} to {target_name!r}"
        ) from exc
    return target_name


def archive_profile(profile: str) -> str:
    """Move one inactive named profile into its local recovery archive."""

    name, source = _named_profile_path(profile)
    _ensure_profile_is_not_active(name)
    if source.is_symlink() or not source.is_dir():
        raise LearningProfileError(f"profile does not exist: {name}")
    archive_root = source.parent / _PROFILE_ARCHIVE_DIR
    target = archive_root / name
    if target.exists() or target.is_symlink():
        raise LearningProfileError(f"archived profile already exists: {name}")
    try:
        archive_root.mkdir(parents=True, exist_ok=True)
        source.rename(target)
    except OSError as exc:
        raise LearningProfileError(f"cannot archive profile: {name}") from exc
    return name


def restore_profile(profile: str) -> str:
    """Restore one named profile from the local recovery archive."""

    name, target = _named_profile_path(profile)
    source = target.parent / _PROFILE_ARCHIVE_DIR / name
    if source.is_symlink() or not source.is_dir():
        raise LearningProfileError(f"archived profile does not exist: {name}")
    if target.exists() or target.is_symlink():
        raise LearningProfileError(f"profile already exists: {name}")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
    except OSError as exc:
        raise LearningProfileError(f"cannot restore profile: {name}") from exc
    return name


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
