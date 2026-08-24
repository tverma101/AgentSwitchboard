"""Deterministic command-shape contracts for literal Claude smoke probes."""

from smoke.lib.claude_cli_matrix import _build_claude_cli_command


def test_background_claude_prompt_is_positional_not_print_mode() -> None:
    command = _build_claude_cli_command(
        claude_bin="claude",
        prompt="run the background probe",
        tools="Bash",
        bare=False,
        extra_args=("--bg",),
    )

    assert "--bg" in command
    assert "-p" not in command
    assert command[-1] == "run the background probe"


def test_foreground_claude_probe_keeps_print_prompt_mode() -> None:
    command = _build_claude_cli_command(
        claude_bin="claude",
        prompt="run the foreground probe",
        tools="",
    )

    assert command[-2:] == ("-p", "run the foreground probe")
