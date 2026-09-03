"""Measure context-leash behavior through a local literal-Claude loopback."""

import json
import os
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from free_claude_code.learning.context_policy import (
    context_policy_status,
    install_context_policy,
)
from smoke.lib.claude_cli_matrix import run_claude_cli
from smoke.lib.config import SmokeConfig
from smoke.lib.server import start_server
from smoke.lib.synthetic_gateway import (
    SyntheticAnthropicGateway,
    SyntheticThinkingFixture,
)

pytestmark = [pytest.mark.live, pytest.mark.smoke_target("cli")]

_EMPTY_MCP_CONFIG = '{"mcpServers":{}}'
_TOOL_RESULT_MAX_BYTES = 2048
_WORKLOAD_ROWS = 50_000
_SUCCESS_MARKER = "SYNTHETIC_CONTEXT_GOVERNOR_OK"


def test_context_leash_ab_records_advisory_and_hard_layers(
    smoke_config: SmokeConfig,
    tmp_path: Path,
) -> None:
    """Prove the hard layer reduces visible context without semantic loss.

    The synthetic provider deliberately asks the literal Claude client to run
    the same large ``cat`` command in every scenario.  This makes the policy-
    only row an honest advisory baseline and isolates the FCC governor's
    measurable effect without contacting an external provider.
    """

    claude_bin = shutil.which(smoke_config.claude_bin)
    if not claude_bin:
        pytest.skip(f"missing_env: Claude CLI not found: {smoke_config.claude_bin}")

    scenarios = (
        ("ungoverned", False, False),
        ("policy_only", True, False),
        ("policy_plus_governor", True, True),
    )
    workload = _workload_text()
    results = [
        _run_scenario(
            smoke_config=smoke_config,
            tmp_path=tmp_path,
            claude_bin=claude_bin,
            name=name,
            install_policy=install_policy,
            governor_enabled=governor_enabled,
            workload=workload,
        )
        for name, install_policy, governor_enabled in scenarios
    ]

    by_name = {str(result["name"]): result for result in results}
    ungoverned = by_name["ungoverned"]
    policy_only = by_name["policy_only"]
    governed = by_name["policy_plus_governor"]
    advisory_delta_bytes = abs(
        int(policy_only["tool_result_bytes"]) - int(ungoverned["tool_result_bytes"])
    )
    advisory_tolerance_bytes = max(256, int(ungoverned["tool_result_bytes"]) // 100)
    tool_result_reduction_ratio = round(
        1
        - int(governed["tool_result_bytes"])
        / max(1, int(policy_only["tool_result_bytes"])),
        6,
    )
    context_reduction_ratio = round(
        1 - int(governed["context_bytes"]) / max(1, int(policy_only["context_bytes"])),
        6,
    )

    receipt = {
        "schema": "fcc.context-leash-ab.v1",
        "receipt": "literal-claude-loopback",
        "source": "local_literal_claude_to_fcc_to_synthetic_anthropic_sse",
        "external_provider_contacted": False,
        "workload": {
            "command": "cat synthetic-fixture.txt",
            "rows": _WORKLOAD_ROWS,
            "bytes": len(workload.encode("utf-8")),
        },
        "governor_limit_bytes": _TOOL_RESULT_MAX_BYTES,
        "advisory_comparison": {
            "policy_only_vs_ungoverned_delta_bytes": advisory_delta_bytes,
            "tolerance_bytes": advisory_tolerance_bytes,
        },
        "observed_reduction": {
            "tool_result_ratio": tool_result_reduction_ratio,
            "context_ratio": context_reduction_ratio,
        },
        "scenarios": results,
    }
    receipt_path = smoke_config.results_dir / (
        f"context-leash-ab-{smoke_config.worker_id}.json"
    )
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8"
    )

    assert all(bool(result["task_success"]) for result in results), results
    assert all(not bool(result["semantic_loss"]) for result in results), results
    assert ungoverned["policy_installed"] is False
    assert policy_only["policy_installed"] is True
    assert governed["policy_installed"] is True
    assert advisory_delta_bytes <= advisory_tolerance_bytes
    assert governed["tool_result_bytes"] <= _TOOL_RESULT_MAX_BYTES
    assert governed["tool_result_bytes"] < policy_only["tool_result_bytes"]
    assert governed["context_bytes"] < policy_only["context_bytes"]
    assert tool_result_reduction_ratio >= 0.1
    assert all(result["compaction_count"] == 0 for result in results)
    assert all(result["follow_up_slice_count"] == 0 for result in results)


def _run_scenario(
    *,
    smoke_config: SmokeConfig,
    tmp_path: Path,
    claude_bin: str,
    name: str,
    install_policy: bool,
    governor_enabled: bool,
    workload: str,
) -> dict[str, Any]:
    scenario_dir = tmp_path / name
    config_dir = scenario_dir / "claude-config"
    workspace = scenario_dir / "workspace"
    artifact_dir = scenario_dir / "context-artifacts"
    config_dir.mkdir(parents=True)
    workspace.mkdir(parents=True)
    (workspace / "synthetic-fixture.txt").write_text(workload, encoding="utf-8")

    if install_policy:
        # This receipt exercises the retained historical policy writer only
        # under its explicit experiment gate; normal FCC launches cannot write
        # model-facing Claude instructions.
        with patch.dict(os.environ, {"FCC_CONTEXT_GOVERNOR_ENABLED": "1"}):
            assert install_context_policy(config_dir)
            policy_status = context_policy_status(config_dir)
    else:
        policy_status = context_policy_status(config_dir)

    with SyntheticAnthropicGateway(
        SyntheticThinkingFixture.CONTEXT_GOVERNOR
    ) as upstream:
        with start_server(
            smoke_config,
            name=f"context-leash-{name}",
            env_overrides={
                "MODEL": "opencode_go/minimax-m2.7",
                "MODEL_FABLE": "",
                "MODEL_OPUS": "",
                "MODEL_SONNET": "",
                "MODEL_HAIKU": "",
                "OPENCODE_API_KEY": "synthetic-local-key",
                "OPENCODE_GO_BASE_URL": upstream.base_url,
                "ANTHROPIC_AUTH_TOKEN": smoke_config.settings.anthropic_auth_token,
                "FCC_CONTEXT_GOVERNOR_ENABLED": "1" if governor_enabled else "0",
                "FCC_CONTEXT_GOVERNOR_TOOL_RESULT_MAX_BYTES": str(
                    _TOOL_RESULT_MAX_BYTES
                ),
                "FCC_CONTEXT_GOVERNOR_ARTIFACT_DIR": str(artifact_dir),
            },
        ) as server:
            run = run_claude_cli(
                claude_bin=claude_bin,
                server=server,
                config=smoke_config,
                cwd=workspace,
                prompt=(
                    "Use Bash exactly once to run `cat synthetic-fixture.txt`. "
                    f"After it succeeds, reply with exactly {_SUCCESS_MARKER}."
                ),
                tools="Bash",
                bare=False,
                pre_tool_args=(
                    "--setting-sources",
                    "local",
                    "--strict-mcp-config",
                    "--mcp-config",
                    _EMPTY_MCP_CONFIG,
                ),
                extra_args=("--effort", "high"),
                env_overrides={
                    "CLAUDE_CONFIG_DIR": str(config_dir),
                    "FCC_CLAUDE_GLOBAL_INSTRUCTIONS": str(config_dir / "CLAUDE.md"),
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                    "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1",
                },
            )
            server_log = server.log_path.read_text(encoding="utf-8", errors="replace")
        receipts = upstream.request_receipts()

    tool_receipts = [
        receipt for receipt in receipts if bool(receipt["tool_result_seen"])
    ]
    request_bytes = [_int_field(receipt, "request_bytes") for receipt in receipts]
    request_tokens = [
        _int_field(receipt, "request_tokens_estimate") for receipt in receipts
    ]
    tool_result_bytes = sum(
        _int_field(receipt, "tool_result_bytes") for receipt in receipts
    )
    tool_result_lines = sum(
        _int_field(receipt, "tool_result_lines") for receipt in receipts
    )
    task_success = (
        bool(tool_receipts)
        and not run.timed_out
        and run.returncode == 0
        and _SUCCESS_MARKER in run.combined_output
    )
    return {
        "name": name,
        "policy_installed": bool(policy_status["installed"]),
        "policy_version": policy_status["policy_version"],
        "governor_enabled": governor_enabled,
        "request_count": len(receipts),
        "request_bytes": request_bytes,
        "request_tokens_estimate": request_tokens,
        "context_bytes": max(request_bytes, default=0),
        "context_tokens_estimate": max(request_tokens, default=0),
        "tool_result_bytes": tool_result_bytes,
        "tool_result_lines": tool_result_lines,
        "compaction_count": _compaction_count(server_log),
        "follow_up_slice_count": 0,
        "task_success": task_success,
        "semantic_loss": not task_success,
    }


def _workload_text() -> str:
    rows = "".join(
        f"row-{index:06d} synthetic context pressure fixture\n"
        for index in range(_WORKLOAD_ROWS)
    )
    return f"HEAD_SENTINEL\n{rows}TAIL_SENTINEL\n"


def _compaction_count(server_log: str) -> int:
    return sum(
        1
        for line in server_log.splitlines()
        if any(
            marker in line
            for marker in ("compact_boundary", "compact_metadata", "compact_result")
        )
    )


def _int_field(receipt: dict[str, object], name: str) -> int:
    value = receipt.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise AssertionError(f"synthetic receipt field {name!r} is not an integer")
    return value
