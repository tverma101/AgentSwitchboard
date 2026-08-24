import json
import sys
from pathlib import Path

import pytest

from free_claude_code.core.anthropic.context_artifact import (
    ContextArtifactError,
    read_context_artifact_slice,
)
from free_claude_code.learning import cli as learning_cli


def test_slice_is_line_and_byte_bounded_with_integrity_metadata(tmp_path: Path) -> None:
    artifact = tmp_path / "tool-result-deadbeef.txt"
    artifact.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    result = read_context_artifact_slice(
        artifact,
        root=tmp_path,
        start_line=2,
        line_count=2,
        max_bytes=512,
    )

    assert result.content == "two\nthree\n"
    assert result.total_lines == 4
    assert result.line_count == 2
    assert result.start_line == 2
    assert result.end_line == 3
    assert result.has_more_before is True
    assert result.has_more_after is True
    assert result.returned_bytes == len(result.content.encode())
    assert len(result.sha256) == 64


def test_slice_clips_one_oversized_line_without_reading_more_visible_bytes(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "tool-result-long.txt"
    artifact.write_text("x" * 2_000 + "\ntail\n", encoding="utf-8")

    result = read_context_artifact_slice(
        artifact,
        root=tmp_path,
        max_bytes=512,
    )

    assert result.returned_bytes <= 512
    assert result.content == "x" * 512
    assert result.end_line == 1
    assert result.has_more_after is True


def test_slice_rejects_path_outside_configured_root(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ContextArtifactError, match="inside FCC"):
        read_context_artifact_slice(outside, root=root)


def test_context_artifact_cli_uses_configured_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "tool-result-cli.txt"
    artifact.write_text("alpha\nbeta\n", encoding="utf-8")
    monkeypatch.setenv("FCC_CONTEXT_GOVERNOR_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fcc-learning",
            "context-artifact",
            "slice",
            str(artifact),
            "--start-line",
            "2",
            "--line-count",
            "1",
        ],
    )

    learning_cli.main()
    response = json.loads(capsys.readouterr().out)

    assert response["content"] == "beta\n"
    assert response["start_line"] == 2
    assert response["has_more_before"] is True
    assert response["has_more_after"] is False
