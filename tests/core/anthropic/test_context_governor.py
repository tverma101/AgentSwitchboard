import hashlib
import json
import stat
from pathlib import Path

import pytest

from free_claude_code.core.anthropic.content import get_block_attr
from free_claude_code.core.anthropic.context_governor import (
    ContextGovernanceError,
    ContextGovernorConfig,
    govern_messages_request,
)
from free_claude_code.core.anthropic.models import Message, MessagesRequest


def _request(content: object) -> MessagesRequest:
    return MessagesRequest(
        model="opencode_go/muse-spark-1.2-contributor",
        messages=[
            Message(
                role="user",
                content=[
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_1",
                        "content": content,
                    }
                ],
            )
        ],
    )


def test_small_text_tool_result_is_unchanged(tmp_path) -> None:
    request = _request("small result")

    governed = govern_messages_request(
        request,
        ContextGovernorConfig(tool_result_max_bytes=4096, artifact_dir=tmp_path),
    )

    assert governed.request is request
    assert governed.records == ()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("limit", [511, 1_000_001])
def test_context_governor_rejects_limits_outside_safe_range(tmp_path, limit) -> None:
    with pytest.raises(ValueError, match="between 512"):
        ContextGovernorConfig(tool_result_max_bytes=limit, artifact_dir=tmp_path)


@pytest.mark.parametrize("limit", [512, 1_000_000])
def test_context_governor_accepts_limits_at_safe_range_edges(tmp_path, limit) -> None:
    config = ContextGovernorConfig(tool_result_max_bytes=limit, artifact_dir=tmp_path)

    assert config.tool_result_max_bytes == limit


def test_large_text_result_is_redirected_to_private_artifact(tmp_path) -> None:
    secret = "do-not-keep-in-artifact"
    text = (
        "HEAD marker\n"
        + f'"api_key": "{secret}"\n'
        + ("middle-line\n" * 20_000)
        + "TAIL marker\n"
    )
    request = _request(text)

    governed = govern_messages_request(
        request,
        ContextGovernorConfig(tool_result_max_bytes=4096, artifact_dir=tmp_path),
    )

    assert len(governed.records) == 1
    record = governed.records[0]
    assert record.tool_use_id == "tool_1"
    assert record.original_bytes == len(text.encode())
    assert record.visible_bytes <= 4096
    assert 0 < record.reduction_ratio < 1
    assert record.original_lines > record.visible_lines > 0
    block = governed.request.messages[0].content[0]
    assert get_block_attr(block, "tool_use_id") == "tool_1"
    replacement = get_block_attr(block, "content")
    assert isinstance(replacement, str)
    assert "tool result redirected" in replacement
    assert "HEAD marker" in replacement
    assert "TAIL marker" in replacement
    assert secret not in replacement
    assert '"api_key": "<redacted>"' in replacement
    assert record.artifact_path in replacement
    trace_fields = record.as_trace_fields()
    assert trace_fields["tool_use_id"] == "tool_1"
    assert secret not in repr(trace_fields)

    artifact = tmp_path / record.artifact_path.rsplit("/", 1)[-1]
    assert artifact.read_text() == text.replace(
        f'"api_key": "{secret}"', '"api_key": "<redacted>"'
    )
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == record.artifact_sha256
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) & 0o077 == 0


def test_existing_artifact_with_digest_prefix_collision_fails_closed(tmp_path) -> None:
    text = "x" * 12_000
    digest = hashlib.sha256(text.encode()).hexdigest()
    artifact = tmp_path / f"tool-result-{digest[:24]}.txt"
    artifact.write_text("stale artifact", encoding="utf-8")
    artifact.chmod(0o600)

    with pytest.raises(ContextGovernanceError, match="different content"):
        govern_messages_request(
            _request(text),
            ContextGovernorConfig(tool_result_max_bytes=4096, artifact_dir=tmp_path),
        )

    assert artifact.read_text(encoding="utf-8") == "stale artifact"


def test_existing_matching_artifact_is_reused_only_when_private(tmp_path) -> None:
    text = "x" * 12_000
    digest = hashlib.sha256(text.encode()).hexdigest()
    artifact = tmp_path / f"tool-result-{digest[:24]}.txt"
    artifact.write_text(text, encoding="utf-8")
    artifact.chmod(0o600)

    governed = govern_messages_request(
        _request(text),
        ContextGovernorConfig(tool_result_max_bytes=4096, artifact_dir=tmp_path),
    )

    assert governed.records[0].artifact_path == str(artifact)
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o600


def test_relative_artifact_directory_is_normalized_for_follow_up_retrieval(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    governed = govern_messages_request(
        _request("x" * 12_000),
        ContextGovernorConfig(
            tool_result_max_bytes=4096,
            artifact_dir=Path("relative-artifacts"),
        ),
    )

    artifact_path = Path(governed.records[0].artifact_path)
    assert artifact_path.is_absolute()
    assert artifact_path.parent == (tmp_path / "relative-artifacts").resolve()


def test_existing_non_private_artifact_is_rejected(tmp_path) -> None:
    text = "x" * 12_000
    digest = hashlib.sha256(text.encode()).hexdigest()
    artifact = tmp_path / f"tool-result-{digest[:24]}.txt"
    artifact.write_text(text, encoding="utf-8")
    artifact.chmod(0o644)

    with pytest.raises(ContextGovernanceError, match="non-private permissions"):
        govern_messages_request(
            _request(text),
            ContextGovernorConfig(tool_result_max_bytes=4096, artifact_dir=tmp_path),
        )


def test_text_block_list_is_governed_as_text(tmp_path) -> None:
    request = _request(
        [
            {"type": "text", "text": "prefix\n"},
            {"type": "text", "text": "x" * 12_000},
            {"type": "text", "text": "\nsuffix"},
        ]
    )

    governed = govern_messages_request(
        request,
        ContextGovernorConfig(tool_result_max_bytes=4096, artifact_dir=tmp_path),
    )

    assert len(governed.records) == 1
    block = governed.request.messages[0].content[0]
    replacement = get_block_attr(block, "content")
    assert isinstance(replacement, str)
    assert "prefix" in replacement
    assert "suffix" in replacement


def test_large_structured_result_is_rejected_without_mutation(tmp_path) -> None:
    content = {"records": ["value" * 1000]}
    request = _request(content)

    with pytest.raises(ContextGovernanceError, match="structured or media"):
        govern_messages_request(
            request,
            ContextGovernorConfig(tool_result_max_bytes=4096, artifact_dir=tmp_path),
        )

    assert not list(tmp_path.iterdir())
    original = request.messages[0].content[0]
    original_content = get_block_attr(original, "content")
    assert json.dumps(original_content) == json.dumps(content)


def test_large_media_result_is_rejected_instead_of_truncated(tmp_path) -> None:
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "x" * 10_000,
            },
        }
    ]
    request = _request(content)

    with pytest.raises(ContextGovernanceError, match="structured or media"):
        govern_messages_request(
            request,
            ContextGovernorConfig(tool_result_max_bytes=4096, artifact_dir=tmp_path),
        )

    assert not list(tmp_path.iterdir())


def test_disabled_governor_does_not_write_artifacts(tmp_path) -> None:
    request = _request("x" * 100_000)

    governed = govern_messages_request(
        request,
        ContextGovernorConfig(
            enabled=False,
            tool_result_max_bytes=4096,
            artifact_dir=tmp_path,
        ),
    )

    assert governed.request is request
    assert governed.records == ()
    assert not list(tmp_path.iterdir())
