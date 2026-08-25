import io
from pathlib import Path

import pytest
from PIL import Image

from free_claude_code.cli import appshot
from free_claude_code.cli.appshot_helpers import (
    copy_appshot_path,
    inspect_appshot,
    open_appshot,
)
from free_claude_code.cli.visuals import build_appshot_attachment, enqueue_appshot
from free_claude_code.core.appshot import AppshotContractError


def _persisted_appshot(tmp_path: Path) -> tuple[Path, Path]:
    output = io.BytesIO()
    Image.new("RGB", (3, 2), "red").save(output, format="PNG")
    source = tmp_path / "source.png"
    source.write_bytes(output.getvalue())
    queue = tmp_path / "queue"
    attachment = build_appshot_attachment(
        source,
        session_id="session-1",
        metadata={"app": "Safari", "window": "localhost:3000"},
    )
    receipt = enqueue_appshot(attachment, root=queue)
    return queue, receipt


def test_persisted_helpers_use_core_receipt_without_exposing_path(tmp_path: Path) -> None:
    queue, receipt = _persisted_appshot(tmp_path)
    receipt_name = Path(receipt.name)

    inspected = inspect_appshot(receipt_name, root=queue)

    assert inspected.startswith("[img ")
    assert "Safari" in inspected
    assert "localhost:3000" in inspected
    assert str(queue.resolve()) not in inspected

    opened: list[Path] = []
    copied: list[Path] = []
    open_appshot(receipt_name, root=queue, opener=opened.append)
    copy_appshot_path(receipt_name, root=queue, copier=copied.append)

    assert len(opened) == 1
    assert copied == opened
    assert opened[0].is_file()
    assert opened[0].is_relative_to(queue.resolve())


def test_persisted_helper_rejects_receipt_name_metadata_mismatch(tmp_path: Path) -> None:
    queue, receipt = _persisted_appshot(tmp_path)
    renamed = receipt.with_name("session-1-deadbeef.json")
    receipt.rename(renamed)

    with pytest.raises(AppshotContractError, match="name does not match"):
        inspect_appshot(Path(renamed.name), root=queue)


def test_cli_inspect_action_does_not_require_session_id(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.delenv("FCC_CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setattr(appshot, "inspect_appshot", lambda receipt, root: "safe card")

    appshot.main(["--inspect", "receipt.json", "--queue", str(tmp_path)])

    assert capsys.readouterr().out.strip() == "safe card"


def test_cli_open_and_copy_actions_do_not_print_resolved_path(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.delenv("FCC_CLAUDE_SESSION_ID", raising=False)
    opened: list[Path] = []
    copied: list[Path] = []
    monkeypatch.setattr(
        appshot,
        "open_appshot",
        lambda receipt, root: opened.append(receipt),
    )
    monkeypatch.setattr(
        appshot,
        "copy_appshot_path",
        lambda receipt, root: copied.append(receipt),
    )

    appshot.main(["--open", "one.json", "--queue", str(tmp_path)])
    open_output = capsys.readouterr().out.strip()
    appshot.main(["--copy-path", "two.json", "--queue", str(tmp_path)])
    copy_output = capsys.readouterr().out.strip()

    assert opened == [Path("one.json")]
    assert copied == [Path("two.json")]
    assert open_output == "opened: one.json"
    assert copy_output == "copied: two.json"
    assert str(tmp_path.resolve()) not in open_output + copy_output
