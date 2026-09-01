"""Launch the native Rust/Ratatui control center against the local FCC Admin API."""

import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from free_claude_code.config.server_urls import local_proxy_root_url
from free_claude_code.config.settings import Settings

_NATIVE_BINARY_ENV = "FCC_CONTROL_TUI_BINARY"
_BINARY_NAME = "fcc-control-center"


class NativeControlCenterUnavailable(RuntimeError):
    """Raised when the native control-center executable cannot be resolved."""


def native_manifest_path() -> Path:
    """Return the packaged Cargo manifest for the native control center."""

    return Path(__file__).resolve().parents[1] / "native_tui" / "Cargo.toml"


def native_control_command(
    settings: Settings,
    *,
    notice: str | None = None,
) -> tuple[str, ...]:
    """Resolve the native binary or a source-backed Cargo launch command."""

    args = ["--base-url", local_proxy_root_url(settings)]
    if notice:
        args.extend(("--notice", notice))

    configured = os.environ.get(_NATIVE_BINARY_ENV, "").strip()
    if configured:
        binary = Path(configured).expanduser()
        if not binary.is_file():
            raise NativeControlCenterUnavailable(
                f"{_NATIVE_BINARY_ENV} does not point to a file: {binary}"
            )
        return (str(binary), *args)

    installed = shutil.which(_BINARY_NAME)
    if installed:
        return (installed, *args)

    cargo = shutil.which("cargo")
    manifest = native_manifest_path()
    if cargo and manifest.is_file():
        return (
            cargo,
            "run",
            "--quiet",
            "--release",
            "--manifest-path",
            str(manifest),
            "--",
            *args,
        )

    raise NativeControlCenterUnavailable(
        "The Rust control center is unavailable. Install Rust/cargo for the "
        "source-backed frontend or set FCC_CONTROL_TUI_BINARY to a built "
        "fcc-control-center executable. Use fcc-server --headless when only "
        "the proxy process is needed."
    )


def run_native_control_center(
    settings: Settings,
    *,
    notice: str | None = None,
) -> None:
    """Run the native control center in the foreground."""

    command = native_control_command(settings, notice=notice)
    completed = subprocess.run(command, check=False)
    if completed.returncode not in {0, 130}:
        raise RuntimeError(
            f"Native AgentSwitchboard control center exited with status "
            f"{completed.returncode}."
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Attach the native TUI to an already-running local FCC server."""

    if argv not in (None, (), []):
        raise SystemExit(
            "fcc-tui does not accept arguments; configure FCC via .env/Admin"
        )
    from free_claude_code.cli import commands

    settings = commands.load_server_settings()
    run_native_control_center(settings)
    return 0
