import json
from pathlib import Path

import pytest

from free_claude_code.learning.hooks import (
    handle_user_prompt,
    install_hooks,
    uninstall_hooks,
)
from free_claude_code.learning.session_end import handle_session_end
from free_claude_code.learning.session_evidence import recover_queued_human_steers
from free_claude_code.learning.session_ledger import SessionEvidenceLedger
from free_claude_code.learning.stop_hook import enqueue_stop
from free_claude_code.learning.store import LearningStore


def _claude_transcript(tmp_path: Path, lines: list[object]) -> tuple[Path, Path]:
    config = tmp_path / ".claude"
    transcript = config / "projects" / "repo" / "session.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        "".join(json.dumps(line) + "\n" for line in lines),
        encoding="utf-8",
    )
    return config, transcript


def _queued(
    prompt: str,
    *,
    session_id: str = "session-1",
    command_mode: str = "prompt",
    source_uuid: str = "steer-1",
    **attachment_extra: object,
) -> dict[str, object]:
    return {
        "type": "attachment",
        "sessionId": session_id,
        "userType": "external",
        "timestamp": "2026-08-30T12:00:00Z",
        "attachment": {
            "type": "queued_command",
            "prompt": prompt,
            "commandMode": command_mode,
            "source_uuid": source_uuid,
            **attachment_extra,
        },
    }


def test_recovers_only_positive_human_queued_command_markers(tmp_path: Path) -> None:
    config, transcript = _claude_transcript(
        tmp_path,
        [
            {"type": "assistant", "message": {"content": "not human"}},
            _queued("Use the already-open browser", source_uuid="human-1"),
            _queued(
                "background agent finished",
                command_mode="task-notification",
                source_uuid="task-1",
            ),
            _queued("meta", source_uuid="meta-1", isMeta=True),
            _queued("internal", source_uuid="origin-1", origin="system"),
        ],
    )

    result = recover_queued_human_steers(
        transcript,
        session_id="session-1",
        claude_config_dir=config,
    )

    assert result.complete is True
    assert result.reason == "ok"
    assert [(item.source_id, item.text) for item in result.steers] == [
        ("human-1", "Use the already-open browser")
    ]


def test_rejects_wrong_session_sidechain_and_nonexternal_records(tmp_path: Path) -> None:
    wrong_session = _queued("wrong", session_id="other", source_uuid="wrong")
    sidechain = _queued("sidechain", source_uuid="side")
    sidechain["isSidechain"] = True
    nonexternal = _queued("internal user", source_uuid="internal")
    nonexternal["userType"] = "internal"
    config, transcript = _claude_transcript(
        tmp_path,
        [wrong_session, sidechain, nonexternal],
    )

    result = recover_queued_human_steers(
        transcript,
        session_id="session-1",
        claude_config_dir=config,
    )

    assert result.complete is True
    assert result.steers == ()


def test_transcript_path_must_remain_inside_claude_projects(tmp_path: Path) -> None:
    config = tmp_path / ".claude"
    (config / "projects").mkdir(parents=True)
    outside = tmp_path / "private.jsonl"
    outside.write_text(json.dumps(_queued("do not read me")) + "\n", encoding="utf-8")

    result = recover_queued_human_steers(
        outside,
        session_id="session-1",
        claude_config_dir=config,
    )

    assert result.complete is False
    assert result.reason == "outside_claude_projects"
    assert result.steers == ()


def test_malformed_transcript_discards_all_partial_steering(tmp_path: Path) -> None:
    config, transcript = _claude_transcript(
        tmp_path,
        [_queued("valid but must not survive", source_uuid="before-error")],
    )
    with transcript.open("a", encoding="utf-8") as stream:
        stream.write("{not json}\n")

    result = recover_queued_human_steers(
        transcript,
        session_id="session-1",
        claude_config_dir=config,
    )

    assert result.complete is False
    assert result.reason == "malformed_jsonl"
    assert result.steers == ()


def test_oversized_transcript_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, transcript = _claude_transcript(
        tmp_path,
        [_queued("steer", source_uuid="one")],
    )
    monkeypatch.setattr(
        "free_claude_code.learning.session_evidence.MAX_TRANSCRIPT_BYTES",
        1,
    )

    result = recover_queued_human_steers(
        transcript,
        session_id="session-1",
        claude_config_dir=config,
    )

    assert result.complete is False
    assert result.reason == "transcript_too_large"
    assert result.steers == ()


def test_human_steering_is_redacted_and_bounded(tmp_path: Path) -> None:
    lines = [
        _queued(
            f"message {index}",
            source_uuid=f"steer-{index}",
        )
        for index in range(6)
    ]
    lines.append(
        _queued(
            "API_KEY=supersecretvalue12345 data:image/png;base64," + "A" * 64,
            source_uuid="secret-steer",
        )
    )
    config, transcript = _claude_transcript(tmp_path, lines)

    result = recover_queued_human_steers(
        transcript,
        session_id="session-1",
        claude_config_dir=config,
        max_items=3,
    )

    assert [item.source_id for item in result.steers] == [
        "steer-4",
        "steer-5",
        "secret-steer",
    ]
    assert "supersecretvalue12345" not in result.steers[-1].text
    assert "REDACTED_SECRET" in result.steers[-1].text
    assert "REDACTED_IMAGE_DATA" in result.steers[-1].text


def test_session_end_persists_only_sanitized_human_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, transcript = _claude_transcript(
        tmp_path,
        [
            {
                "type": "tool_result",
                "sessionId": "session-1",
                "content": "RAW_TOOL_OUTPUT_CANARY",
            },
            _queued(
                "Switch to provider B API_KEY=supersecretvalue12345",
                source_uuid="human-steer",
            ),
        ],
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    store = LearningStore(tmp_path / "learning.db")

    handle_session_end(
        {
            "session_id": "session-1",
            "cwd": str(tmp_path / "repo"),
            "transcript_path": str(transcript),
        },
        store,
    )

    ledger = SessionEvidenceLedger(store)
    evidence = ledger.list_evidence("session-1")
    assert len(evidence) == 1
    assert evidence[0].kind == "human_steer"
    assert "supersecretvalue12345" not in evidence[0].text
    assert "RAW_TOOL_OUTPUT_CANARY" not in evidence[0].text
    assert str(transcript) not in evidence[0].text
    state = ledger.session_end_state("session-1")
    assert state is not None
    assert state["transcript_complete"] == 1
    assert state["transcript_reason"] == "ok"


def test_incomplete_session_end_stores_no_partial_human_steer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, transcript = _claude_transcript(
        tmp_path,
        [_queued("must be discarded", source_uuid="partial")],
    )
    with transcript.open("a", encoding="utf-8") as stream:
        stream.write("not-json\n")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    store = LearningStore(tmp_path / "learning.db")

    handle_session_end(
        {
            "session_id": "session-1",
            "cwd": str(tmp_path),
            "transcript_path": str(transcript),
        },
        store,
    )

    ledger = SessionEvidenceLedger(store)
    assert ledger.list_evidence("session-1") == []
    state = ledger.session_end_state("session-1")
    assert state is not None
    assert state["transcript_complete"] == 0
    assert state["transcript_reason"] == "malformed_jsonl"


def test_user_prompt_and_stop_stage_idempotent_session_evidence(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / "learning.db")
    handle_user_prompt(
        {
            "session_id": "session-1",
            "cwd": str(tmp_path),
            "prompt": "Fix the parser",
            "uuid": "prompt-1",
        },
        store,
    )
    payload = {
        "session_id": "session-1",
        "cwd": str(tmp_path),
        "last_assistant_message": "Parser fixed and tests passed.",
    }

    first = enqueue_stop(payload, store)
    second = enqueue_stop(payload, store)

    assert first is not None
    assert first == second
    evidence = SessionEvidenceLedger(store).list_evidence("session-1")
    assert [(item.kind, item.source_id) for item in evidence] == [
        ("human_prompt", "prompt-1"),
        ("turn_result", first),
    ]


def test_session_end_hook_installs_and_uninstalls_with_fcc_hooks(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")

    assert install_hooks(tmp_path)
    payload = json.loads(settings.read_text(encoding="utf-8"))
    session_end_commands = [
        hook["command"]
        for group in payload["hooks"]["SessionEnd"]
        for hook in group["hooks"]
    ]
    assert len(session_end_commands) == 1
    assert "free_claude_code.learning.session_end" in session_end_commands[0]

    assert uninstall_hooks(tmp_path)
    restored = json.loads(settings.read_text(encoding="utf-8"))
    assert "SessionEnd" not in restored.get("hooks", {})
