import json

import httpx
import pytest

from smoke.lib.synthetic_gateway import (
    SyntheticAnthropicGateway,
    SyntheticThinkingFixture,
    fixture_names,
)


@pytest.mark.parametrize("fixture", tuple(SyntheticThinkingFixture))
def test_synthetic_gateway_serves_every_fixture_without_external_network(
    fixture: SyntheticThinkingFixture,
) -> None:
    with SyntheticAnthropicGateway(fixture) as gateway:
        response = httpx.post(
            f"{gateway.base_url}/messages",
            json={
                "model": "minimax-m2.7",
                "messages": [{"role": "user", "content": "secret prompt"}],
            },
            timeout=5,
        )

    assert response.status_code == 200
    assert "message_start" in response.text
    if fixture is SyntheticThinkingFixture.REDACTED_THINKING:
        assert "redacted_thinking" in response.text
    elif fixture is SyntheticThinkingFixture.TOOL_ROUNDTRIP:
        assert "tool_use" in response.text
    else:
        assert "content_block_start" in response.text


def test_synthetic_gateway_tool_fixture_records_structural_continuation_only() -> None:
    with SyntheticAnthropicGateway(SyntheticThinkingFixture.TOOL_ROUNDTRIP) as gateway:
        first = httpx.post(
            f"{gateway.base_url}/messages",
            json={
                "model": "minimax-m2.7",
                "messages": [{"role": "user", "content": "secret prompt"}],
                "tools": [{"name": "Read"}],
            },
            timeout=5,
        )
        second = httpx.post(
            f"{gateway.base_url}/messages",
            json={
                "model": "minimax-m2.7",
                "messages": [
                    {"role": "user", "content": "secret prompt"},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "toolu_synthetic_read",
                                "content": "secret tool output",
                            }
                        ],
                    },
                ],
            },
            timeout=5,
        )
        receipts = gateway.request_receipts()

    assert first.status_code == second.status_code == 200
    assert "tool_use" in first.text
    assert "SYNTHETIC_TOOL_CONTINUATION" in second.text
    assert len(receipts) == 2
    assert receipts[0]["tool_result_seen"] is False
    assert receipts[1]["tool_result_seen"] is True
    assert "secret" not in json.dumps(receipts)


def test_synthetic_fixture_names_are_stable_and_complete() -> None:
    assert fixture_names() == tuple(
        fixture.value for fixture in SyntheticThinkingFixture
    )
