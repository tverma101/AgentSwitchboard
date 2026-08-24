import json
import os
from typing import Any

import httpx
import pytest

from free_claude_code.config.model_refs import parse_provider_type
from smoke.lib.config import ProviderModel, SmokeConfig
from smoke.lib.e2e import ConversationDriver, SmokeServerDriver
from smoke.lib.http import REASONING_SAFE_OUTPUT_TOKENS, post_json
from smoke.lib.server import RunningServer
from smoke.lib.skips import skip_if_upstream_unavailable_exception

pytestmark = [pytest.mark.live, pytest.mark.smoke_target("api")]


def test_probe_and_models_routes(
    smoke_server: RunningServer, smoke_headers: dict[str, str]
) -> None:
    with httpx.Client(base_url=smoke_server.base_url, headers=smoke_headers) as client:
        assert client.get("/health").json()["status"] == "healthy"

        root = client.get("/")
        assert root.status_code == 200
        assert root.json()["status"] == "ok"

        models = client.get("/v1/models")
        assert models.status_code == 200
        assert models.json()["data"]

        for path in (
            "/",
            "/health",
            "/v1/messages",
            "/v1/responses",
            "/v1/messages/count_tokens",
        ):
            head = client.head(path)
            assert head.status_code == 204, (path, head.status_code, head.text)
            options = client.options(path)
            assert options.status_code == 204, (path, options.status_code, options.text)


def test_count_tokens_accepts_thinking_tools_and_results(
    smoke_server: RunningServer,
    smoke_config: SmokeConfig,
    smoke_headers: dict[str, str],
) -> None:
    payload: dict[str, Any] = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [
            {"role": "user", "content": "Use the tool."},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Need to inspect the file."},
                    {
                        "type": "tool_use",
                        "id": "toolu_smoke",
                        "name": "Read",
                        "input": {"file_path": "README.md"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_smoke",
                        "content": "Free Claude Code",
                    }
                ],
            },
        ],
        "tools": [
            {
                "name": "Read",
                "description": "Read a file",
                "input_schema": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            }
        ],
    }
    response = post_json(
        smoke_server,
        "/v1/messages/count_tokens",
        payload,
        smoke_config,
        headers=smoke_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["input_tokens"] > 0


def test_muse_reasoning_boundaries_when_requested(
    smoke_config: SmokeConfig,
) -> None:
    """Prove explicit off/minimal Messages intent reaches the Go/Muse route."""

    if os.getenv("FCC_SMOKE_REASONING_BOUNDARIES") != "1":
        pytest.skip(
            "set FCC_SMOKE_REASONING_BOUNDARIES=1 to run the live reasoning boundary"
        )
    model_ref = os.getenv(
        "FCC_SMOKE_REASONING_BOUNDARY_MODEL",
        "opencode_go/muse-spark-1.2-contributor",
    )
    provider = parse_provider_type(model_ref)
    if "/" not in model_ref or not smoke_config.has_provider_configuration(provider):
        pytest.skip(
            "missing_env: FCC_SMOKE_REASONING_BOUNDARY_MODEL needs configured "
            "OpenCode Go credentials"
        )

    provider_model = ProviderModel(
        provider=provider,
        full_model=model_ref,
        source="FCC_SMOKE_REASONING_BOUNDARY_MODEL",
    )
    cases: tuple[tuple[str, dict[str, Any]], ...] = (
        ("off", {"thinking": {"type": "disabled"}}),
        ("minimal", {"output_config": {"effort": "minimal"}}),
    )
    with SmokeServerDriver(
        smoke_config,
        name="api-reasoning-boundaries",
        env_overrides={
            "MODEL": provider_model.full_model,
            "MESSAGING_PLATFORM": "none",
            "LOG_LEVEL": "DEBUG",
        },
    ).run() as server:
        driver = ConversationDriver(server, smoke_config)
        for label, extra in cases:
            try:
                turn = driver.stream(
                    {
                        "model": "claude-sonnet-4-5-20250929",
                        # Muse can spend a small output budget on hidden
                        # reasoning before emitting its short marker. Keep
                        # this boundary probe above that budget so it tests
                        # routing semantics rather than manufacturing an
                        # incomplete upstream response.
                        "max_tokens": REASONING_SAFE_OUTPUT_TOKENS,
                        "messages": [
                            {
                                "role": "user",
                                "content": f"Reply with exactly FCC_REASONING_{label.upper()}.",
                            }
                        ],
                        **extra,
                    }
                )
            except Exception as exc:
                skip_if_upstream_unavailable_exception(exc)
                raise
            assert turn.events
        server_log = server.log_path.read_text(encoding="utf-8", errors="replace")

    route_records = []
    provider_records = []
    for line in server_log.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") == "free_claude_code.api.route.resolved":
            route_records.append(record)
        elif record.get("event") == "provider.fault_attribution":
            provider_records.append(record)

    assert [record["reasoning_control"] for record in route_records[-2:]] == [
        "off",
        "default",
    ]
    assert route_records[-1]["reasoning_effort"] == "minimal"
    assert [record["provider"] for record in provider_records[-2:]] == [
        "OPENCODE_GO",
        "OPENCODE_GO",
    ]
    assert [record["protocol"] for record in provider_records[-2:]] == [
        "responses",
        "responses",
    ]
    assert provider_records[-1]["requested_reasoning_effort"] == "minimal"


def test_optimization_fast_paths_do_not_need_provider(
    smoke_server: RunningServer,
    smoke_config: SmokeConfig,
    smoke_headers: dict[str, str],
) -> None:
    cases: tuple[tuple[str, dict[str, Any], str], ...] = (
        (
            "quota",
            {
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "quota"}],
            },
            "Quota check passed.",
        ),
        (
            "title",
            {
                "model": "claude-3-5-sonnet-20241022",
                "system": (
                    "Generate a concise, sentence-case title (3-7 words). "
                    'Return JSON with a single "title" field.'
                ),
                "messages": [{"role": "user", "content": "hello"}],
            },
            "Conversation",
        ),
        (
            "prefix",
            {
                "model": "claude-3-5-sonnet-20241022",
                "messages": [
                    {
                        "role": "user",
                        "content": "<policy_spec>extract command</policy_spec>\nCommand: git status --short",
                    }
                ],
            },
            "git",
        ),
        (
            "suggestion",
            {
                "model": "claude-3-5-sonnet-20241022",
                "messages": [{"role": "user", "content": "[SUGGESTION MODE: next]"}],
            },
            "",
        ),
        (
            "filepath",
            {
                "model": "claude-3-5-sonnet-20241022",
                "system": "Extract any file paths that this command output contains.",
                "messages": [
                    {
                        "role": "user",
                        "content": "Command: cat smoke/test_api_live.py\nOutput: file contents\n<filepaths>",
                    }
                ],
            },
            "smoke/test_api_live.py",
        ),
    )
    for name, payload, expected_text in cases:
        response = post_json(
            smoke_server, "/v1/messages", payload, smoke_config, headers=smoke_headers
        )
        assert response.status_code == 200, (name, response.text)
        text = response.json()["content"][0]["text"]
        assert expected_text in text


def test_invalid_messages_returns_anthropic_error(
    smoke_server: RunningServer,
    smoke_config: SmokeConfig,
    smoke_headers: dict[str, str],
) -> None:
    response = post_json(
        smoke_server,
        "/v1/messages",
        {"model": "claude-3-5-sonnet-20241022", "messages": []},
        smoke_config,
        headers=smoke_headers,
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["type"] == "error"
    assert payload["error"]["type"] == "invalid_request_error"


def test_stop_endpoint_reports_no_messaging(
    smoke_server: RunningServer, smoke_headers: dict[str, str]
) -> None:
    response = httpx.post(
        f"{smoke_server.base_url}/stop",
        headers=smoke_headers,
        timeout=5,
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Messaging system not initialized"
