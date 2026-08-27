"""Tests for the opt-in Codespaces burst command contract."""

from free_claude_code.cli import burst


def test_burst_defaults_to_two_core_codespaces_machine() -> None:
    args = burst._parser().parse_args([])

    assert args.machine == "basicLinux32gb"
    assert args.idle_timeout == "10m"
    assert args.action == "run"


def test_burst_supports_explicit_stop_action() -> None:
    args = burst._parser().parse_args(["stop"])

    assert args.action == "stop"


def test_burst_selects_named_codespace_before_single_fallback() -> None:
    named = burst.Codespace("named", "Shutdown", "Rumple Harness Burst")
    other = burst.Codespace("other", "Available", "Unrelated")

    assert burst._select_codespace([other, named]) == named


def test_burst_rejects_ambiguous_codespaces() -> None:
    first = burst.Codespace("first", "Shutdown", "One")
    second = burst.Codespace("second", "Shutdown", "Two")

    try:
        burst._select_codespace([first, second])
    except burst.BurstError as exc:
        assert "multiple Rumple Codespaces" in str(exc)
    else:
        raise AssertionError("ambiguous Codespaces should be rejected")
