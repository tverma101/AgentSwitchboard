"""Tests for the personal fork's terminal-only Admin readiness reporting."""

from pathlib import Path
from unittest.mock import patch

from free_claude_code.cli import commands
from free_claude_code.config.settings import Settings


def _settings() -> Settings:
    return Settings.model_construct(host="0.0.0.0", port=8082)


def test_report_admin_when_ready_never_launches_a_browser(
    capsys,
) -> None:
    settings = _settings()
    with patch.object(commands, "preflight_proxy", return_value=None):
        assert commands.report_admin_when_ready(settings) is True

    output = capsys.readouterr().out
    assert "terminal-only mode" in output
    assert "http://127.0.0.1:8082/admin" in output


def test_schedule_report_admin_ready_uses_a_terminal_named_worker() -> None:
    settings = _settings()
    started: list[tuple[str, object]] = []

    class ImmediateThread:
        def __init__(self, *, target, args, name, daemon) -> None:
            started.append((name, target))
            assert args == (settings,)
            assert daemon is True

        def start(self) -> None:
            return None

    with patch.object(commands.threading, "Thread", ImmediateThread):
        commands.schedule_report_admin_ready(settings)

    assert started == [("fcc-report-admin-ready", commands.report_admin_when_ready)]


def test_terminal_only_module_does_not_retain_browser_launcher_imports() -> None:
    source = Path(commands.__file__).read_text(encoding="utf-8")

    assert "import webbrowser" not in source
    assert "terminal-browser" not in source
