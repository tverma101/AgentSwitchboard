import base64
import io
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from free_claude_code.cli import attachment
from free_claude_code.cli.attachment import (
    AttachmentSourceError,
    main,
    read_image_source,
)


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (3, 2), "red").save(output, format="PNG")
    return output.getvalue()


def test_path_source_detects_media_type_and_uses_basename(tmp_path: Path) -> None:
    image = tmp_path / "private" / "screenshot.png"
    image.parent.mkdir()
    image.write_bytes(_png_bytes())

    data, media_type, label = read_image_source(path=image)

    assert data == _png_bytes()
    assert media_type == "image/png"
    assert label == "screenshot.png"


def test_cli_path_prints_card_without_full_path_or_image_payload(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    image = tmp_path / "secret-screenshot.png"
    data = _png_bytes()
    image.write_bytes(data)

    main(["--path", str(image), "--no-preview"])

    output = capsys.readouterr().out
    assert output.startswith("[img ")
    assert "secret-screenshot.png" in output
    assert str(tmp_path) not in output
    assert base64.b64encode(data).decode() not in output


def test_clipboard_source_decodes_png_without_persisting_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _png_bytes()
    commands: list[list[str]] = []

    monkeypatch.setattr(attachment.sys, "platform", "darwin")
    monkeypatch.setattr(attachment.shutil, "which", lambda _: "/usr/bin/swift")

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command, 0, base64.b64encode(data).decode() + "\n", ""
        )

    monkeypatch.setattr(attachment.subprocess, "run", fake_run)

    decoded, media_type, label = read_image_source(clipboard=True)

    assert decoded == data
    assert media_type == "image/png"
    assert label == "clipboard-image"
    assert commands and commands[0][:2] == ["/usr/bin/swift", "-e"]


def test_clipboard_source_requires_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(attachment.sys, "platform", "linux")

    with pytest.raises(AttachmentSourceError, match="requires macOS"):
        read_image_source(clipboard=True)


def test_missing_source_is_rejected_before_rendering() -> None:
    with pytest.raises(AttachmentSourceError, match="regular file"):
        read_image_source(path=Path("/definitely/missing/image.png"))
