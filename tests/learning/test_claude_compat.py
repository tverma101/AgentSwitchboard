import json
import stat
import sys

from free_claude_code.cli.claude_firewall import ensure_process_wrapper
from free_claude_code.learning import cli as learning_cli


def test_claude_compat_cli_reports_certified_runtime(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    binary = tmp_path / "claude"
    binary.write_text("#!/bin/sh\nprintf '%s\\n' 2.1.228", encoding="utf-8")
    binary.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    ensure_process_wrapper()

    monkeypatch.setattr(
        sys,
        "argv",
        ["fcc-learning", "claude-compat", "--binary", str(binary)],
    )
    learning_cli.main()

    status = json.loads(capsys.readouterr().out)
    assert status["claude_version"] == "2.1.228"
    assert status["state"] == "certified"
    assert status["process_wrapper_valid"] is True
