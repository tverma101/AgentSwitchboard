from pathlib import Path

from free_claude_code.core.anthropic.content import get_block_attr
from free_claude_code.core.anthropic.context_artifact import (
    read_context_artifact_slice,
)
from free_claude_code.core.anthropic.context_governor import (
    ContextGovernorConfig,
    govern_messages_request,
)
from free_claude_code.core.anthropic.models import Message, MessagesRequest


def test_governed_5mb_result_round_trips_through_bounded_artifact_reader(
    tmp_path: Path,
) -> None:
    target_bytes = 5 * 1024 * 1024
    line = "deterministic-context-line-0123456789\n"
    text = line * ((target_bytes // len(line)) + 1)
    request = MessagesRequest(
        model="opencode_go/muse-spark-1.2-contributor",
        messages=[
            Message(
                role="user",
                content=[
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-large",
                        "content": text,
                    }
                ],
            )
        ],
    )

    governed = govern_messages_request(
        request,
        ContextGovernorConfig(tool_result_max_bytes=4096, artifact_dir=tmp_path),
    )

    record = governed.records[0]
    replacement = get_block_attr(governed.request.messages[0].content[0], "content")
    assert isinstance(replacement, str)
    assert record.original_bytes >= target_bytes
    assert record.visible_bytes <= 4096
    assert text not in replacement

    bounded = read_context_artifact_slice(
        record.artifact_path,
        root=tmp_path,
        start_line=2,
        line_count=4,
        max_bytes=512,
    )

    assert bounded.sha256 == record.artifact_sha256
    assert bounded.path.startswith(str(tmp_path.resolve()))
    assert bounded.returned_bytes <= 512
    assert bounded.line_count <= 4
    assert bounded.has_more_before is True
    assert bounded.has_more_after is True
