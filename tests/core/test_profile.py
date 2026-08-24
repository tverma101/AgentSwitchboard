"""Deterministic launch-bound profile identity contracts."""

import pytest

from free_claude_code.core.profile import (
    ProfileIdentity,
    ProfileNameError,
    current_profile,
    profile_context,
    resolve_profile,
)


def test_profile_identity_normalizes_and_has_stable_receipt_fields() -> None:
    identity = ProfileIdentity("  Coding_Work  ")

    assert identity.name == "coding_work"
    assert identity.namespace == "fcc.learning.profile/coding_work"
    assert identity.receipt() == {
        "profile": "coding_work",
        "profile_namespace": "fcc.learning.profile/coding_work",
        "profile_schema": "fcc.learning.profile",
        "profile_version": 1,
    }

    with pytest.raises(ProfileNameError):
        ProfileIdentity("../unsafe")


def test_profile_context_is_scoped_and_does_not_mutate_launch_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FCC_LEARNING_PROFILE", "default")
    assert current_profile().name == "default"

    with profile_context("research"):
        assert current_profile() == resolve_profile("research")

    assert current_profile().name == "default"
