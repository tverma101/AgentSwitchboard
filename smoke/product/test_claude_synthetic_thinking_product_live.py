"""Characterize the installed Claude CLI against local Anthropic SSE fixtures."""

import json
import shutil
from pathlib import Path

import pytest

from smoke.lib.claude_cli_matrix import run_claude_cli
from smoke.lib.config import SmokeConfig
from smoke.lib.server import start_server
from smoke.lib.synthetic_gateway import (
    SyntheticAnthropicGateway,
    SyntheticThinkingFixture,
)

pytestmark = [pytest.mark.live, pytest.mark.smoke_target("cli")]

_TOOL_FIXTURES = frozenset(
    {
        SyntheticThinkingFixture.TOOL_ROUNDTRIP,
        SyntheticThinkingFixture.THINKING_TOOL_ROUNDTRIP,
        SyntheticThinkingFixture.OPAQUE_TOOL_ROUNDTRIP,
    }
)
_FIXTURE_MARKERS = {
    SyntheticThinkingFixture.VISIBLE_SUMMARY: "SYNTHETIC_SUMMARY_OK",
    SyntheticThinkingFixture.VISIBLE_THINKING: "SYNTHETIC_THINKING_OK",
    SyntheticThinkingFixture.EMPTY_THINKING: "SYNTHETIC_EMPTY_THINKING_OK",
    SyntheticThinkingFixture.EMPTY_THINKING_SIGNATURE: "SYNTHETIC_EMPTY_THINKING_OK",
    SyntheticThinkingFixture.UNSUPPORTED_THINKING: "SYNTHETIC_UNSUPPORTED_THINKING_OK",
}


@pytest.mark.parametrize(
    "fixture",
    (
        SyntheticThinkingFixture.VISIBLE_SUMMARY,
        SyntheticThinkingFixture.VISIBLE_THINKING,
        SyntheticThinkingFixture.EMPTY_THINKING,
        SyntheticThinkingFixture.EMPTY_THINKING_SIGNATURE,
        SyntheticThinkingFixture.REDACTED_THINKING,
        SyntheticThinkingFixture.UNSUPPORTED_THINKING,
        SyntheticThinkingFixture.USAGE_ONLY,
        SyntheticThinkingFixture.TOOL_ROUNDTRIP,
        SyntheticThinkingFixture.THINKING_TOOL_ROUNDTRIP,
        SyntheticThinkingFixture.OPAQUE_TOOL_ROUNDTRIP,
    ),
)
def test_installed_claude_round_trips_local_thinking_fixture(
    smoke_config: SmokeConfig,
    tmp_path: Path,
    fixture: SyntheticThinkingFixture,
) -> None:
    """Prove the literal client reaches FCC and never needs a paid upstream."""

    claude_bin = shutil.which(smoke_config.claude_bin)
    if not claude_bin:
        pytest.skip(f"missing_env: Claude CLI not found: {smoke_config.claude_bin}")

    workspace = tmp_path / fixture.value
    workspace.mkdir(parents=True)
    if fixture in _TOOL_FIXTURES:
        (workspace / "synthetic-fixture.txt").write_text(
            "SYNTHETIC_FILE_TOKEN", encoding="utf-8"
        )

    with SyntheticAnthropicGateway(fixture) as upstream:
        with start_server(
            smoke_config,
            name=f"claude-synthetic-{fixture.value}",
            env_overrides={
                "MODEL": "opencode_go/minimax-m2.7",
                "MODEL_FABLE": "",
                "MODEL_OPUS": "",
                "MODEL_SONNET": "",
                "MODEL_HAIKU": "",
                "OPENCODE_API_KEY": "synthetic-local-key",
                "OPENCODE_GO_BASE_URL": upstream.base_url,
                "ANTHROPIC_AUTH_TOKEN": smoke_config.settings.anthropic_auth_token,
                "MESSAGING_PLATFORM": "none",
            },
        ) as server:
            run = run_claude_cli(
                claude_bin=claude_bin,
                server=server,
                config=smoke_config,
                cwd=workspace,
                prompt=(
                    "Use Read once on synthetic-fixture.txt and then reply with "
                    "exactly SYNTHETIC_TOOL_CONTINUATION."
                    if fixture in _TOOL_FIXTURES
                    else (
                        "Reply with exactly "
                        f"{_FIXTURE_MARKERS.get(fixture, 'SYNTHETIC_THINKING_OK')}."
                    )
                ),
                tools="Read" if fixture in _TOOL_FIXTURES else "",
                bare=False,
                pre_tool_args=(
                    "--setting-sources",
                    "local",
                    "--strict-mcp-config",
                    "--mcp-config",
                    '{"mcpServers":{}}',
                ),
                extra_args=("--effort", "high"),
                env_overrides={
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                },
            )
            server_log = server.log_path.read_text(encoding="utf-8", errors="replace")
        receipts = upstream.request_receipts()

    assert receipts, "Claude did not reach the local synthetic upstream through FCC"
    assert all(receipt["model"] == "minimax-m2.7" for receipt in receipts)
    assert upstream.base_url.startswith("http://127.0.0.1:")
    assert "POST /v1/messages" in server_log
    assert "api.anthropic.com" not in server_log
    assert "api.openai.com" not in server_log
    assert not run.timed_out, run.combined_output
    if fixture in _TOOL_FIXTURES:
        assert any(receipt["tool_result_seen"] for receipt in receipts)
    elif fixture in {
        SyntheticThinkingFixture.REDACTED_THINKING,
        SyntheticThinkingFixture.USAGE_ONLY,
    }:
        assert run.returncode == 0, run.combined_output
    else:
        marker = _FIXTURE_MARKERS.get(fixture)
        assert marker is not None
        assert marker in run.combined_output or run.returncode == 0

    receipt_path = smoke_config.results_dir / (
        f"claude-synthetic-thinking-{fixture.value}-{smoke_config.worker_id}.json"
    )
    receipt_path.write_text(
        json.dumps(
            {
                "fixture": fixture.value,
                "client_binary": Path(run.command[0]).name if run.command else None,
                "client_returncode": run.returncode,
                "timed_out": run.timed_out,
                "client_presentation": {
                    "stdout_nonempty": bool(run.stdout.strip()),
                    "stderr_nonempty": bool(run.stderr.strip()),
                    "thinking_delta_observed": "thinking_delta" in run.combined_output,
                    "tool_result_roundtrip": any(
                        receipt["tool_result_seen"] for receipt in receipts
                    ),
                },
                "request_receipts": receipts,
                "evidence": "local_claude_to_fcc_to_synthetic_anthropic_sse",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
