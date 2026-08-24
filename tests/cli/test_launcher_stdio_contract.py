from unittest.mock import MagicMock, patch

import pytest

from free_claude_code.cli.launchers.common import run_client_process


def test_client_launcher_inherits_terminal_stdio() -> None:
    process = MagicMock()
    process.pid = 4242
    process.wait.return_value = 0

    with (
        patch(
            "free_claude_code.cli.launchers.common.subprocess.Popen",
            return_value=process,
        ) as popen,
        patch("free_claude_code.cli.launchers.common.register_pid"),
        patch("free_claude_code.cli.launchers.common.unregister_pid"),
        pytest.raises(SystemExit) as exc_info,
    ):
        run_client_process(
            command=["claude", "--version"],
            env={"PATH": "/usr/bin"},
            binary_name="claude",
            display_name="Claude Code",
            install_hint="install Claude Code",
        )

    assert exc_info.value.code == 0
    popen.assert_called_once_with(
        ["claude", "--version"],
        env={"PATH": "/usr/bin"},
    )
    kwargs = popen.call_args.kwargs
    assert "stdin" not in kwargs
    assert "stdout" not in kwargs
    assert "stderr" not in kwargs
