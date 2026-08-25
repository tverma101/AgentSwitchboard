from pathlib import Path

from free_claude_code.cli import appshot


def test_appshot_cli_uses_explicit_session_and_prints_local_receipt(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    image = tmp_path / "captured.png"
    image.write_bytes(_png_bytes())

    monkeypatch.setattr(
        appshot,
        "capture_and_enqueue_appshot",
        lambda *, session_id, root, session_source: (
            _attachment(session_id, image),
            tmp_path / "queue" / "session-1.json",
        ),
    )

    appshot.main(["--session-id", "session-1", "--queue", str(tmp_path / "queue")])
    output = capsys.readouterr().out
    assert "[appshot:" in output
    assert "session-1.json" in output


def test_appshot_cli_can_list_pending_session_receipts(tmp_path: Path, capsys) -> None:
    queue = tmp_path / "queue"
    queue.mkdir()
    (queue / "session-1-a.json").write_text("{}\n", encoding="utf-8")
    (queue / "session-1-b.json").write_text("{}\n", encoding="utf-8")
    (queue / "other-a.json").write_text("{}\n", encoding="utf-8")

    appshot.main(["--session-id", "session-1", "--queue", str(queue), "--list"])

    assert capsys.readouterr().out.splitlines() == [
        "session-1-a.json",
        "session-1-b.json",
    ]


def _attachment(session_id: str, image: Path):
    from free_claude_code.cli.visuals import build_appshot_attachment

    return build_appshot_attachment(
        image,
        session_id=session_id,
        metadata={"app": "Safari", "window": "localhost:3000"},
    )


def _png_bytes() -> bytes:
    import io

    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (3, 2), "red").save(output, format="PNG")
    return output.getvalue()
