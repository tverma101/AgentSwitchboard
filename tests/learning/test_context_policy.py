"""Tests for the explicit global Claude context-policy manager."""

import json
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
    assert status["installed"] is True
    assert status["policy_version"] == "1"
    assert status["policy_digest"] == policy_digest()
    assert status["backup_exists"] is True
    assert (tmp_path / "CLAUDE.md.fcc-context-policy.bak").read_text(
        encoding="utf-8"
    ) == original


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
