"""Launch-bound profile identity shared by runtime and learning boundaries."""

import contextvars
import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field

PROFILE_ENV = "FCC_LEARNING_PROFILE"
DEFAULT_PROFILE = "default"
PROFILE_SCHEMA = "fcc.learning.profile"
PROFILE_VERSION = 1

_PROFILE_RE = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,31})\Z")


class ProfileNameError(ValueError):
    """Raised when a profile name is unsafe or invalid."""


class ProfileSwitchError(RuntimeError):
    """Raised when a live session would be rebound to another profile."""


def normalize_profile(profile: str | None) -> str:
    """Normalize and validate one profile identifier."""

    if profile is None:
        value = DEFAULT_PROFILE
    elif isinstance(profile, str):
        value = profile.strip().casefold()
    else:
        raise ProfileNameError(
            "profile must use 1-32 lowercase letters, digits, '.', '_' or '-'"
        )
    if not _PROFILE_RE.fullmatch(value):
        raise ProfileNameError(
            "profile must use 1-32 lowercase letters, digits, '.', '_' or '-'"
        )
    return value


@dataclass(frozen=True, slots=True)
class ProfileIdentity:
    """Stable, serializable identity captured at a process/session boundary."""

    name: str
    schema: str = PROFILE_SCHEMA
    version: int = PROFILE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", normalize_profile(self.name))
        if self.schema != PROFILE_SCHEMA:
            raise ProfileNameError(f"unsupported profile schema: {self.schema!r}")
        if self.version != PROFILE_VERSION:
            raise ProfileNameError(f"unsupported profile version: {self.version!r}")

    @property
    def namespace(self) -> str:
        """Return the non-path namespace used in diagnostics and receipts."""

        return f"{self.schema}/{self.name}"

    def receipt(self) -> dict[str, str | int]:
        """Return safe identity fields for diagnostics and metadata receipts."""

        return {
            "profile": self.name,
            "profile_namespace": self.namespace,
            "profile_schema": self.schema,
            "profile_version": self.version,
        }


def resolve_profile(
    profile: str | ProfileIdentity | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> ProfileIdentity:
    """Resolve one profile once from an explicit name or launch environment."""

    if isinstance(profile, ProfileIdentity):
        return profile
    values = os.environ if environment is None else environment
    return ProfileIdentity(profile if profile is not None else values.get(PROFILE_ENV))


_CURRENT_PROFILE: contextvars.ContextVar[ProfileIdentity | None] = (
    contextvars.ContextVar("fcc_current_profile", default=None)
)


def current_profile() -> ProfileIdentity:
    """Return the request/task profile, falling back to the launch environment."""

    selected = _CURRENT_PROFILE.get()
    return selected if selected is not None else resolve_profile()


@contextmanager
def profile_context(
    profile: str | ProfileIdentity | None = None,
) -> Iterator[ProfileIdentity]:
    """Bind one immutable profile to the current synchronous/async context."""

    selected = resolve_profile(profile)
    token = _CURRENT_PROFILE.set(selected)
    try:
        yield selected
    finally:
        _CURRENT_PROFILE.reset(token)


@dataclass(frozen=True, slots=True)
class ProfileLease:
    """A live session's immutable profile binding."""

    profile: ProfileIdentity
    session_id: str

    def require(self, profile: str | ProfileIdentity | None) -> None:
        """Reject an attempt to rebind this live session to another profile."""

        selected = resolve_profile(profile)
        if selected != self.profile:
            raise ProfileSwitchError(
                f"profile {self.profile.name!r} is fixed for live session "
                f"{self.session_id!r}; start a new session to use {selected.name!r}"
            )


@dataclass(slots=True)
class ProfileRuntime:
    """Small in-process selector that refuses live-session profile switches."""

    _active: ProfileIdentity
    _live_session_ids: set[str] = field(default_factory=set)

    def __init__(self, profile: str | ProfileIdentity | None = None) -> None:
        self._active = resolve_profile(profile)
        self._live_session_ids = set()

    @property
    def active_profile(self) -> ProfileIdentity:
        """Return the current launch/session selection."""

        return self._active

    def switch(self, profile: str | ProfileIdentity | None) -> ProfileIdentity:
        """Select a profile only before a different live session is active."""

        selected = resolve_profile(profile)
        if self._live_session_ids and selected != self._active:
            raise ProfileSwitchError(
                f"cannot switch from profile {self._active.name!r} while "
                f"session(s) are live: {', '.join(sorted(self._live_session_ids))}"
            )
        self._active = selected
        return selected

    def start_session(self, session_id: str) -> ProfileLease:
        """Bind a session id to the current profile and return its lease."""

        normalized_id = session_id.strip()
        if not normalized_id:
            raise ValueError("session_id must not be empty")
        self._live_session_ids.add(normalized_id)
        return ProfileLease(self._active, normalized_id)

    def end_session(self, session_id: str) -> None:
        """Release one local live-session binding."""

        self._live_session_ids.discard(session_id.strip())

    @contextmanager
    def session(self, session_id: str) -> Iterator[ProfileLease]:
        """Bind a profile context for one bounded session lifetime."""

        lease = self.start_session(session_id)
        try:
            with profile_context(lease.profile):
                yield lease
        finally:
            self.end_session(lease.session_id)


__all__ = [
    "DEFAULT_PROFILE",
    "PROFILE_ENV",
    "PROFILE_SCHEMA",
    "PROFILE_VERSION",
    "ProfileIdentity",
    "ProfileLease",
    "ProfileNameError",
    "ProfileRuntime",
    "ProfileSwitchError",
    "current_profile",
    "normalize_profile",
    "profile_context",
    "resolve_profile",
]
