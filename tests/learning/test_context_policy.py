"""Tests for the explicit global Claude context-policy manager."""

import json
import stat
import sys
from pathlib import Path

import pytest

from free_claude_code.learning import cli as learning_cli
from free_claude_code.learning.context_policy import (
    POLICY_BEGIN,
    POLICY_END,
    context_policy_status,
    install_context_policy,
    instructions_path,
    policy_block,
    policy_digest,
    uninstall_context_policy,
)


@pytest.fixture(autouse=True)
def _enable_legacy_writer_for_unit_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the retained writer only under its explicit experiment gate."""

    monkeypatch.setenv("FCC_CONTEXT_GOVERNOR_ENABLED", "1")


def test_install_is_disabled_without_explicit_experiment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "CLAUDE.md"
    original = "# Personal instructions\n"
    path.write_text(original, encoding="utf-8")
    monkeypatch.delenv("FCC_CONTEXT_GOVERNOR_ENABLED")

    assert install_context_policy(tmp_path) is False
    assert path.read_text(encoding="utf-8") == original
    status = context_policy_status(tmp_path)
    assert status["enabled"] is False
    assert status["installed"] is False


def test_install_is_idempotent_and_preserves_user_instructions(tmp_path: Path) -> None:
    original = "# Personal instructions\n\nPrefer small, verified changes.\n"
    path = tmp_path / "CLAUDE.md"
    path.write_text(original, encoding="utf-8")

    assert install_context_policy(tmp_path)
    installed = path.read_text(encoding="utf-8")
    assert original in installed
    assert installed.count(POLICY_BEGIN) == 1
    assert installed.count(POLICY_END) == 1
    assert not install_context_policy(tmp_path)
    assert path.read_text(encoding="utf-8") == installed

    status = context_policy_status(tmp_path)
    assert status["enabled"] is True
    assert status["installed"] is True
    assert status["policy_version"] == "1"
    assert status["policy_digest"] == policy_digest()
    assert status["backup_exists"] is True
    assert (tmp_path / "CLAUDE.md.fcc-context-policy.bak").read_text(
        encoding="utf-8"
    ) == original
    assert (
        stat.S_IMODE((tmp_path / "CLAUDE.md.fcc-context-policy.bak").stat().st_mode)
        == 0o600
    )


def test_update_replaces_only_the_managed_block(tmp_path: Path) -> None:
    prefix = "# Before\n\nkeep this byte-for-byte\n\n"
    suffix = "\n\n# After\nkeep this too\n"
    path = tmp_path / "CLAUDE.md"
    path.write_text(f"{prefix}{policy_block()}{suffix}", encoding="utf-8")

    assert install_context_policy(tmp_path) is False
    assert path.read_text(encoding="utf-8") == f"{prefix}{policy_block()}{suffix}"

    path.write_text(
        f"{prefix}{POLICY_BEGIN}\n<!-- old policy -->\n{POLICY_END}{suffix}",
        encoding="utf-8",
    )
    assert install_context_policy(tmp_path)
    updated = path.read_text(encoding="utf-8")
    assert updated == f"{prefix}{policy_block()}{suffix}"
    assert updated.startswith(prefix)
    assert updated.endswith(suffix)


def test_uninstall_removes_only_the_managed_block(tmp_path: Path) -> None:
    original = "# User rules\n\nDo not expose credentials.\n"
    path = tmp_path / "CLAUDE.md"
    path.write_text(original, encoding="utf-8")
    assert install_context_policy(tmp_path)
    path.write_text(
        f"{path.read_text(encoding='utf-8')}\n# Added after install\n",
        encoding="utf-8",
    )

    assert uninstall_context_policy(tmp_path)
    remaining = path.read_text(encoding="utf-8")
    assert POLICY_BEGIN not in remaining
    assert POLICY_END not in remaining
    assert original in remaining
    assert "# Added after install" in remaining
    assert not uninstall_context_policy(tmp_path)


def test_duplicate_markers_fail_closed_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "CLAUDE.md"
    original = (
        f"{POLICY_BEGIN}\nfirst\n{POLICY_END}\n{POLICY_BEGIN}\nsecond\n{POLICY_END}"
    )
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="markers are missing or duplicated"):
        install_context_policy(tmp_path)
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    "document",
    (
        f"prefix {POLICY_BEGIN}\nbody\n{POLICY_END}\n",
        f"{POLICY_BEGIN}\nbody\n{POLICY_END} suffix\n",
        f"{POLICY_END}\nbody\n{POLICY_BEGIN}\n",
        f"{POLICY_BEGIN}\nbody\n",
    ),
)
def test_conflicting_markers_fail_closed_without_mutation(
    tmp_path: Path, document: str
) -> None:
    path = tmp_path / "CLAUDE.md"
    path.write_text(document, encoding="utf-8")

    with pytest.raises(ValueError, match="cannot safely update"):
        install_context_policy(tmp_path)
    assert path.read_text(encoding="utf-8") == document
    assert not (tmp_path / "CLAUDE.md.fcc-context-policy.bak").exists()


def test_uninstall_creates_recovery_copy_before_first_mutation(tmp_path: Path) -> None:
    original = f"# User rules\n\n{policy_block()}\n\n# Tail\n"
    path = tmp_path / "CLAUDE.md"
    path.write_text(original, encoding="utf-8")

    assert uninstall_context_policy(tmp_path)
    assert path.read_text(encoding="utf-8") == "# User rules\n\n\n\n# Tail\n"
    assert (tmp_path / "CLAUDE.md.fcc-context-policy.bak").read_text(
        encoding="utf-8"
    ) == original


def test_symlink_target_fails_closed_without_mutation(tmp_path: Path) -> None:
    target = tmp_path / "real-claude.md"
    target.write_text("# Keep this content\n", encoding="utf-8")
    path = tmp_path / "CLAUDE.md"
    try:
        path.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(ValueError, match="symbolic link"):
        install_context_policy(tmp_path)
    assert path.is_symlink()
    assert target.read_text(encoding="utf-8") == "# Keep this content\n"
    assert not (tmp_path / "CLAUDE.md.fcc-context-policy.bak").exists()


def test_existing_policy_file_preserves_mode_and_status_does_not_expose_user_text(
    tmp_path: Path,
) -> None:
    secret = "API_KEY=do-not-print-this-value"
    path = tmp_path / "CLAUDE.md"
    path.write_text(f"# Private rules\n{secret}\n", encoding="utf-8")
    path.chmod(0o640)

    assert install_context_policy(tmp_path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    status = context_policy_status(tmp_path)
    assert secret not in json.dumps(status, sort_keys=True)
    assert secret not in policy_block()


def test_new_policy_file_is_private(tmp_path: Path) -> None:
    assert install_context_policy(tmp_path)
    assert stat.S_IMODE((tmp_path / "CLAUDE.md").stat().st_mode) == 0o600


def test_cli_context_policy_status_uses_explicit_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    instructions = tmp_path / "global.md"
    monkeypatch.setenv("FCC_CLAUDE_GLOBAL_INSTRUCTIONS", str(instructions))
    assert instructions_path() == instructions

    monkeypatch.setattr(sys, "argv", ["fcc-learning", "context-policy", "install"])
    learning_cli.main()
    install_receipt = json.loads(capsys.readouterr().out)
    assert install_receipt["changed"] is True
    assert install_receipt["path"] == str(instructions)

    monkeypatch.setattr(sys, "argv", ["fcc-learning", "context-policy", "status"])
    learning_cli.main()
    status = json.loads(capsys.readouterr().out)
    assert status["installed"] is True
    assert status["policy_digest"] == policy_digest()
