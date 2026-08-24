"""Deterministic command-shape contracts for literal Claude smoke probes."""

import json
import subprocess
from pathlib import Path
from typing import cast

from free_claude_code.config.settings import Settings
from smoke.lib.claude_cli_matrix import (
    ClaudeCliRun,
    _attached_prompt_ready,
    _attached_prompt_suggestion_visible,
    _build_attached_claude_command,
    _build_claude_cli_command,
    _extract_background_session_id,
    _run_probe,
    token_evidence,
)
from smoke.lib.config import DEFAULT_TARGETS, ProviderModel, SmokeConfig
from smoke.lib.server import RunningServer


def _smoke_config(tmp_path: Path) -> SmokeConfig:
    return SmokeConfig(
        root=tmp_path,
        results_dir=tmp_path / ".smoke-results",
        live=False,
        interactive=False,
        targets=DEFAULT_TARGETS,
        provider_matrix=frozenset(),
        timeout_s=45.0,
        prompt="Reply with exactly: FCC_SMOKE_PONG",
        claude_bin="claude",
        worker_id="test-worker",
        settings=Settings.model_construct(anthropic_auth_token=""),
    )


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
    assert "--output-format" not in command
    assert "--include-partial-messages" not in command
    assert "--verbose" not in command
    assert command[-1] == "run the background probe"


def test_foreground_claude_probe_keeps_print_prompt_mode() -> None:
    command = _build_claude_cli_command(
        claude_bin="claude",
        prompt="run the foreground probe",
        tools="",
    )

    assert command[-2:] == ("-p", "run the foreground probe")


def test_background_handle_is_extracted_for_terminal_attach() -> None:
    run = ClaudeCliRun(
        command=("claude", "--bg"),
        returncode=0,
        stdout="backgrounded · 2c91c5f2 (idle — send a prompt to start)",
        stderr="",
        duration_s=0.01,
    )

    assert _extract_background_session_id(run) == "2c91c5f2"


def test_background_attach_uses_screen_reader_terminal_mode() -> None:
    assert _build_attached_claude_command(
        claude_bin="fccdanger", session_id="2c91c5f2"
    ) == (
        "fccdanger",
        "attach",
        "2c91c5f2",
    )


def test_attached_prompt_waits_for_screen_reader_input_line() -> None:
    assert not _attached_prompt_ready("manual mode on\neffort: xhigh")
    assert _attached_prompt_ready("manual mode on\neffort: xhigh\n$ ")
    assert not _attached_prompt_ready(f'{chr(0x276F)} Try "create a file that..."')
    assert _attached_prompt_suggestion_visible(
        f'{chr(0x276F)} Try "create a file that..."'
    )
    assert _attached_prompt_ready(
        f'ctrl+g to edit in VS Code\n{chr(0x276F)} Try "create a file that..."'
    )


def test_cli_probe_pins_selected_provider_model_in_child_environment(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run_claude_cli(**kwargs: object) -> ClaudeCliRun:
        captured.update(kwargs)
        return ClaudeCliRun(
            command=("claude", "-p", "FCC_MODEL_ROUTE"),
            returncode=0,
            stdout="FCC_MODEL_ROUTE",
            stderr="",
            duration_s=0.01,
        )

    monkeypatch.setattr(
        "smoke.lib.claude_cli_matrix.run_claude_cli", fake_run_claude_cli
    )
    server = RunningServer(
        base_url="http://127.0.0.1:9999",
        port=9999,
        log_path=tmp_path / "server.log",
        process=cast(subprocess.Popen[bytes], object()),
    )

    outcome = _run_probe(
        claude_bin="claude",
        server=server,
        smoke_config=_smoke_config(tmp_path),
        provider_model=ProviderModel(
            provider="opencode_go",
            full_model="opencode_go/muse-spark-1.2-contributor",
            source="test",
        ),
        workspace=tmp_path / "workspace",
        feature="model_route",
        marker="FCC_MODEL_ROUTE",
        prompt="Reply with the marker.",
        tools="",
    )

    assert captured["env_overrides"] == {
        "HOST": "127.0.0.1",
        "PORT": "9999",
        "MODEL": "opencode_go/muse-spark-1.2-contributor",
    }
    assert outcome.classification == "passed"


def test_token_evidence_summarizes_provider_receipts_without_payloads() -> None:
    run = ClaudeCliRun(
        command=("claude", "-p", "marker"),
        returncode=0,
        stdout="marker",
        stderr="",
        duration_s=0.1,
    )
    records = "\n".join(
        json.dumps(
            {
                "event": "provider.fault_attribution",
                "provider": "OPENCODE_GO",
                "protocol": "responses",
                "outcome": "completed",
                "attempt_number": 1,
                "http_status": None,
                "terminal_event": "response.completed",
                "duration_ms": 120,
                "time_to_first_token_ms": 80,
                "request_shape_hash": "request-hash",
                "stable_prefix_hash": "prefix-hash",
            }
        )
        for _ in range(2)
    )

    evidence = token_evidence(
        feature="text",
        marker="marker",
        run=run,
        log_delta=records,
    )

    assert evidence["provider_ids"] == ["OPENCODE_GO"]
    assert evidence["upstream_protocols"] == ["responses"]
    assert evidence["completed_provider_turns"] == 2
    assert evidence["upstream_attempts_total"] == 2
    assert evidence["upstream_attempts_per_completed_turn"] == 1.0
    assert evidence["provider_http_error_count"] == 0
    assert evidence["response_completed_event_count"] == 2
    assert evidence["request_shape_hash_count"] == 1
    assert evidence["stable_prefix_hash_count"] == 1
    assert evidence["duration_ms"] == {"min": 120.0, "max": 120.0}
    assert evidence["time_to_first_token_ms"] == {"min": 80.0, "max": 80.0}
