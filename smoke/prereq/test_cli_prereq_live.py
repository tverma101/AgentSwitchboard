import json
import os
import shutil
from pathlib import Path

import pytest

from free_claude_code.cli.claude_env import build_claude_proxy_env
from free_claude_code.cli.managed.session import ManagedClaudeSession
from free_claude_code.config.model_refs import parse_provider_type
from smoke.lib.child_process import (
    cmd_fcc_server,
    run_captured_text,
)
from smoke.lib.claude_cli_matrix import (
    CLAUDE_REASONING_EFFORT_OPTIONS,
    CLAUDE_REASONING_EFFORTS,
    run_auto_compact_probe,
    run_background_subagent_probe,
    run_reasoning_effort_matrix,
    run_subagent_probe,
    write_matrix_report,
)
from smoke.lib.config import ProviderModel, SmokeConfig
from smoke.lib.server import start_server
from smoke.lib.skips import skip_upstream_unavailable

pytestmark = [pytest.mark.live, pytest.mark.smoke_target("cli")]


def test_fcc_server_entrypoint_starts_server(smoke_config: SmokeConfig) -> None:
    with start_server(
        smoke_config,
        command=cmd_fcc_server(),
        env_overrides={"MESSAGING_PLATFORM": "none"},
        name="entrypoint",
    ) as server:
        assert server.process.poll() is None


def test_claude_cli_prompt_when_available(
    smoke_config: SmokeConfig, tmp_path: Path
) -> None:
    claude_bin = shutil.which(smoke_config.claude_bin)
    if not claude_bin:
        pytest.skip(f"Claude CLI not found: {smoke_config.claude_bin}")
    models = smoke_config.provider_models()
    if not models:
        pytest.skip("no configured provider model available for Claude CLI smoke")

    with start_server(
        smoke_config,
        env_overrides={"MODEL": models[0].full_model, "MESSAGING_PLATFORM": "none"},
        name="claude-cli",
    ) as server:
        env = build_claude_proxy_env(
            proxy_root_url=server.base_url,
            auth_token=smoke_config.settings.anthropic_auth_token,
            base_env=os.environ,
        )
        result = run_captured_text(
            [claude_bin, "-p", "Reply with exactly FCC_SMOKE_PONG"],
            cwd=tmp_path,
            env=env,
            timeout=smoke_config.timeout_s,
            check=False,
        )
        server_log = server.log_path.read_text(encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stderr or result.stdout
    assert "GET /v1/models" in server_log, (
        "Claude CLI did not discover models from the local gateway"
    )
    assert "POST /v1/messages" in server_log, (
        "Claude CLI did not call the local Anthropic-compatible endpoint"
    )
    if "FCC_SMOKE_PONG" not in result.stdout:
        skip_upstream_unavailable(
            "Claude CLI reached the local proxy but returned no smoke token"
        )


def test_claude_cli_auto_compact_resume_when_requested(
    smoke_config: SmokeConfig, tmp_path: Path
) -> None:
    """Require an automatic compact boundary before the post-boundary tool turn."""
    claude_bin = shutil.which(smoke_config.claude_bin)
    if not claude_bin:
        pytest.skip(f"Claude CLI not found: {smoke_config.claude_bin}")

    model_ref = os.getenv("FCC_SMOKE_AUTO_COMPACT_MODEL")
    if model_ref:
        provider = parse_provider_type(model_ref)
        if "/" not in model_ref or not smoke_config.has_provider_configuration(
            provider
        ):
            pytest.skip(
                "missing_env: FCC_SMOKE_AUTO_COMPACT_MODEL needs a configured "
                "provider/model reference"
            )
        provider_model = ProviderModel(
            provider=provider,
            full_model=model_ref,
            source="FCC_SMOKE_AUTO_COMPACT_MODEL",
        )
    else:
        models = smoke_config.provider_models()
        if not models:
            pytest.skip("no configured provider model available for auto-compact")
        provider_model = models[0]

    with start_server(
        smoke_config,
        env_overrides={
            "MODEL": provider_model.full_model,
            "MESSAGING_PLATFORM": "none",
            "LOG_LEVEL": "DEBUG",
        },
        name="claude-auto-compact",
    ) as server:
        outcome = run_auto_compact_probe(
            claude_bin=claude_bin,
            server=server,
            smoke_config=smoke_config,
            provider_model=provider_model,
            model_dir=tmp_path,
            marker_prefix="CLI",
        )
        report_path = write_matrix_report(
            smoke_config,
            [outcome],
            target="cli_auto_compact",
            filename_prefix="claude-auto-compact",
        )

    if outcome.classification == "upstream_unavailable":
        skip_upstream_unavailable(
            f"automatic compaction reached FCC but upstream was unavailable; "
            f"report={report_path}"
        )
    assert outcome.classification == "passed", (
        f"automatic compaction gate failed; report={report_path}; "
        f"evidence={outcome.token_evidence}"
    )


def test_claude_cli_reasoning_effort_matrix_when_requested(
    smoke_config: SmokeConfig, tmp_path: Path
) -> None:
    """Prove each installed Claude effort level reaches FCC as requested."""
    if os.getenv("FCC_SMOKE_REASONING_MATRIX") != "1":
        pytest.skip("set FCC_SMOKE_REASONING_MATRIX=1 to run the live effort matrix")

    claude_bin = shutil.which(smoke_config.claude_bin)
    if not claude_bin:
        pytest.skip(f"Claude CLI not found: {smoke_config.claude_bin}")

    model_ref = os.getenv("FCC_SMOKE_REASONING_MODEL")
    if model_ref:
        provider = parse_provider_type(model_ref)
        if "/" not in model_ref or not smoke_config.has_provider_configuration(
            provider
        ):
            pytest.skip(
                "missing_env: FCC_SMOKE_REASONING_MODEL needs a configured "
                "provider/model reference"
            )
        provider_model = ProviderModel(
            provider=provider,
            full_model=model_ref,
            source="FCC_SMOKE_REASONING_MODEL",
        )
    else:
        models = smoke_config.provider_models()
        if not models:
            pytest.skip("no configured provider model available for reasoning matrix")
        provider_model = models[0]

    raw_efforts = os.getenv("FCC_SMOKE_REASONING_EFFORTS")
    efforts = CLAUDE_REASONING_EFFORTS
    if raw_efforts:
        efforts = tuple(
            dict.fromkeys(
                item.strip() for item in raw_efforts.split(",") if item.strip()
            )
        )
        unknown = sorted(set(efforts) - set(CLAUDE_REASONING_EFFORT_OPTIONS))
        if unknown:
            pytest.skip(
                "FCC_SMOKE_REASONING_EFFORTS contains unsupported values: "
                + ", ".join(unknown)
                + "; Claude 2.1.228 advertises only low, medium, high, xhigh, max"
            )

    with start_server(
        smoke_config,
        env_overrides={
            "MODEL": provider_model.full_model,
            "MESSAGING_PLATFORM": "none",
            "LOG_LEVEL": "DEBUG",
        },
        name="claude-reasoning-matrix",
    ) as server:
        outcomes = run_reasoning_effort_matrix(
            claude_bin=claude_bin,
            server=server,
            smoke_config=smoke_config,
            provider_model=provider_model,
            model_dir=tmp_path,
            marker_prefix="CLI",
            efforts=efforts,
        )
        report_path = write_matrix_report(
            smoke_config,
            outcomes,
            target="cli_reasoning_effort_matrix",
            filename_prefix="claude-reasoning-effort",
        )

    if any(outcome.classification == "upstream_unavailable" for outcome in outcomes):
        skip_upstream_unavailable(
            f"reasoning effort matrix reached FCC but upstream was unavailable; "
            f"report={report_path}"
        )

    failures = [
        f"{outcome.feature}: {outcome.classification}"
        for outcome in outcomes
        if outcome.classification != "passed"
    ]
    assert not failures, (
        f"reasoning effort matrix failed; report={report_path}: {failures}"
    )
    for effort, outcome in zip(efforts, outcomes, strict=True):
        assert outcome.token_evidence["reasoning_effort_values"] == [effort], (
            f"{effort} was not traced as the sole requested effort: "
            f"{outcome.token_evidence}; report={report_path}"
        )


def test_claude_cli_subagent_when_requested(
    smoke_config: SmokeConfig, tmp_path: Path
) -> None:
    """Prove a foreground Claude Agent subtask stays on the local gateway."""
    if os.getenv("FCC_SMOKE_SUBAGENT") != "1":
        pytest.skip("set FCC_SMOKE_SUBAGENT=1 to run the live subagent probe")

    claude_bin = shutil.which(smoke_config.claude_bin)
    if not claude_bin:
        pytest.skip(f"Claude CLI not found: {smoke_config.claude_bin}")

    model_ref = os.getenv("FCC_SMOKE_SUBAGENT_MODEL")
    if model_ref:
        provider = parse_provider_type(model_ref)
        if "/" not in model_ref or not smoke_config.has_provider_configuration(
            provider
        ):
            pytest.skip(
                "missing_env: FCC_SMOKE_SUBAGENT_MODEL needs a configured "
                "provider/model reference"
            )
        provider_model = ProviderModel(
            provider=provider,
            full_model=model_ref,
            source="FCC_SMOKE_SUBAGENT_MODEL",
        )
    else:
        models = smoke_config.provider_models()
        if not models:
            pytest.skip("no configured provider model available for subagent")
        provider_model = models[0]

    with start_server(
        smoke_config,
        env_overrides={
            "MODEL": provider_model.full_model,
            "MESSAGING_PLATFORM": "none",
            "LOG_LEVEL": "DEBUG",
            "LOG_RAW_API_PAYLOADS": "true",
        },
        name="claude-subagent",
    ) as server:
        outcome = run_subagent_probe(
            claude_bin=claude_bin,
            server=server,
            smoke_config=smoke_config,
            provider_model=provider_model,
            model_dir=tmp_path,
            marker_prefix="CLI",
        )
        report_path = write_matrix_report(
            smoke_config,
            [outcome],
            target="cli_subagent",
            filename_prefix="claude-subagent",
        )

    if outcome.classification == "upstream_unavailable":
        skip_upstream_unavailable(
            f"subagent reached FCC but upstream was unavailable; report={report_path}"
        )
    assert outcome.classification == "passed", (
        f"subagent probe failed; report={report_path}; "
        f"evidence={outcome.token_evidence}"
    )


def test_claude_cli_background_subagent_when_requested(
    smoke_config: SmokeConfig, tmp_path: Path
) -> None:
    """Prove a background Claude Agent subtask stays on the local gateway."""
    if os.getenv("FCC_SMOKE_BACKGROUND_SUBAGENT") != "1":
        pytest.skip(
            "set FCC_SMOKE_BACKGROUND_SUBAGENT=1 to run the live background probe"
        )

    claude_bin = shutil.which(smoke_config.claude_bin)
    if not claude_bin:
        pytest.skip(f"Claude CLI not found: {smoke_config.claude_bin}")

    model_ref = os.getenv(
        "FCC_SMOKE_BACKGROUND_SUBAGENT_MODEL", os.getenv("FCC_SMOKE_SUBAGENT_MODEL")
    )
    if model_ref:
        provider = parse_provider_type(model_ref)
        if "/" not in model_ref or not smoke_config.has_provider_configuration(
            provider
        ):
            pytest.skip(
                "missing_env: FCC_SMOKE_BACKGROUND_SUBAGENT_MODEL needs a "
                "configured provider/model reference"
            )
        provider_model = ProviderModel(
            provider=provider,
            full_model=model_ref,
            source="FCC_SMOKE_BACKGROUND_SUBAGENT_MODEL",
        )
    else:
        models = smoke_config.provider_models()
        if not models:
            pytest.skip(
                "no configured provider model available for background subagent"
            )
        provider_model = models[0]

    with start_server(
        smoke_config,
        env_overrides={
            "MODEL": provider_model.full_model,
            "MESSAGING_PLATFORM": "none",
            "LOG_LEVEL": "DEBUG",
            "LOG_RAW_API_PAYLOADS": "true",
        },
        name="claude-background-subagent",
    ) as server:
        outcome = run_background_subagent_probe(
            claude_bin=claude_bin,
            server=server,
            smoke_config=smoke_config,
            provider_model=provider_model,
            model_dir=tmp_path,
            marker_prefix="CLI",
        )
        report_path = write_matrix_report(
            smoke_config,
            [outcome],
            target="cli_background_subagent",
            filename_prefix="claude-background-subagent",
        )

    if outcome.classification == "upstream_unavailable":
        skip_upstream_unavailable(
            "background subagent reached FCC but upstream was unavailable; "
            f"report={report_path}"
        )
    assert outcome.classification == "passed", (
        f"background subagent probe failed; report={report_path}; "
        f"evidence={outcome.token_evidence}"
    )


@pytest.mark.asyncio
async def test_managed_claude_fresh_resume_fork_roundtrip_when_requested(
    smoke_config: SmokeConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove managed Claude fresh, resume, and fork tasks stay on FCC."""
    claude_bin = shutil.which(smoke_config.claude_bin)
    if not claude_bin:
        pytest.skip(f"Claude CLI not found: {smoke_config.claude_bin}")

    model_ref = os.getenv("FCC_SMOKE_MANAGED_MODEL")
    if model_ref:
        provider = parse_provider_type(model_ref)
        if "/" not in model_ref or not smoke_config.has_provider_configuration(
            provider
        ):
            pytest.skip(
                "missing_env: FCC_SMOKE_MANAGED_MODEL needs a configured "
                "provider/model reference"
            )
        provider_model = ProviderModel(
            provider=provider,
            full_model=model_ref,
            source="FCC_SMOKE_MANAGED_MODEL",
        )
    else:
        models = smoke_config.provider_models()
        if not models:
            pytest.skip("no configured provider model available for managed Claude")
        provider_model = models[0]

    with start_server(
        smoke_config,
        env_overrides={
            "MODEL_FABLE": provider_model.full_model,
            "MESSAGING_PLATFORM": "none",
            "LOG_LEVEL": "DEBUG",
        },
        name="managed-claude-resume",
    ) as server:
        # Keep the literal child away from the user's settings, state, and hooks
        # after the isolated server has inherited the configured credentials.
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
        monkeypatch.setenv("FCC_LEARNING_ENABLED", "0")
        monkeypatch.delenv("CLAUDE_CODE_SIMPLE", raising=False)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        session = ManagedClaudeSession(
            workspace_path=str(workspace),
            proxy_root_url=server.base_url,
            claude_bin=claude_bin,
            auth_token=smoke_config.settings.anthropic_auth_token,
        )
        try:
            fresh_events = [
                event
                async for event in session.start_task(
                    "Reply with exactly FCC_MANAGED_FRESH"
                )
            ]
            session_id = session.current_session_id
            if not session_id:
                pytest.fail("managed Claude did not emit a resumable session id")

            resumed_events = [
                event
                async for event in session.start_task(
                    "Reply with exactly FCC_MANAGED_RESUMED",
                    session_id=session_id,
                )
            ]
            fork_events = [
                event
                async for event in session.start_task(
                    "Reply with exactly FCC_MANAGED_FORKED",
                    session_id=session_id,
                    fork_session=True,
                )
            ]
        finally:
            await session.stop()

        server_log = server.log_path.read_text(encoding="utf-8", errors="replace")

    serialized = json.dumps([fresh_events, resumed_events, fork_events], sort_keys=True)
    combined = f"{serialized}\n{server_log}".lower()
    if any(
        marker in combined
        for marker in (
            "upstream_unavailable",
            "connection refused",
            "rate limit",
            "overloaded",
            "provider api request failed",
        )
    ):
        skip_upstream_unavailable(
            "managed Claude reached FCC but the configured upstream was unavailable"
        )

    assert "FCC_MANAGED_FRESH" in serialized
    assert "FCC_MANAGED_RESUMED" in serialized
    assert "FCC_MANAGED_FORKED" in serialized
    assert [
        event.get("code")
        for event in (*fresh_events, *resumed_events, *fork_events)
        if event.get("type") == "exit"
    ] == [0, 0, 0]
    assert server_log.count("POST /v1/messages") >= 3
