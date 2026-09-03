"""Launch the native Rust/Ratatui control center against the local FCC Admin API."""

import difflib
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from free_claude_code.config.server_urls import local_proxy_root_url
from free_claude_code.config.settings import Settings

_NATIVE_BINARY_ENV = "FCC_CONTROL_TUI_BINARY"
_BINARY_NAME = "fcc-control-center"

_TUI_USAGE = (
    "fcc-tui [path] [--goto <file:line:col>] [--diff <a> <b>] [--review] "
    "[--split <right|left|up|down> [--size <fraction>]] [--theme <name>] "
    "[--timing] [--shortcut-setup] [--list-commands] [--build]"
)

#: Native control-center theme and command inventory. The UI is intentionally
#: not a code-editor/workbench shell; file-oriented compatibility flags remain
#: bounded CLI conveniences, while the visible TUI exposes FCC pages/actions.
_SUPPORTED_THEMES = ("dark",)
_SPLIT_DIRECTIONS = ("right", "left", "up", "down")

#: Mirrors the Rust palette inventory in
#: ``src/free_claude_code/native_tui/src/app.rs`` (titles must stay in sync;
#: ``test_palette_commands_cover_every_page`` guards the page coverage).
PALETTE_COMMANDS: tuple[str, ...] = (
    "Go to Dashboard",
    "Go to Providers",
    "Go to Models",
    "Go to Routing",
    "Go to Context Window",
    "Go to Local Setup",
    "Go to Settings",
    "Go to Usage",
    "Go to Diagnostics",
    "Refresh current view",
    "Toggle page navigation",
    "Toggle status panel",
    "Focus page navigation",
    "Focus page",
    "Launch Claude",
    "Launch Claude with danger permissions",
    "Open command palette",
    "Quit control center",
    "Configure selected provider",
    "Test selected provider",
    "Add custom provider",
    "Edit custom provider",
    "Delete custom provider",
    "Sign in connected account",
    "Disconnect connected account",
    "Search models",
    "Choose model provider",
    "Toggle selected models",
    "Disable all models",
    "Set MODEL to selected model",
    "Edit selected field",
    "Toggle advanced fields",
    "Run route diagnostic",
)


class NativeControlCenterUnavailable(RuntimeError):
    """Raised when the native control-center executable cannot be resolved."""


class TuiUsageError(ValueError):
    """Raised when `fcc-tui` arguments cannot be honored."""


@dataclass(frozen=True, slots=True)
class TuiOptions:
    """Parsed `fcc-tui` invocation."""

    workspace: Path | None = None
    goto_file: Path | None = None
    goto_line: int | None = None
    goto_col: int | None = None
    diff_a: Path | None = None
    diff_b: Path | None = None
    review: bool = False
    split: str | None = None
    split_size: float | None = None
    theme: str = "dark"
    timing: bool = False
    shortcut_setup: bool = False
    list_commands: bool = False
    build_native: bool = False
    notice_parts: tuple[str, ...] = field(default_factory=tuple)


def parse_tui_argv(argv: Sequence[str]) -> TuiOptions:
    """Parse `fcc-tui` arguments, failing closed on anything unhonorable."""

    args = list(argv)
    workspace: Path | None = None
    goto_file: Path | None = None
    goto_line: int | None = None
    goto_col: int | None = None
    diff_a: Path | None = None
    diff_b: Path | None = None
    review = False
    split: str | None = None
    split_size: float | None = None
    theme = "dark"
    timing = False
    shortcut_setup = False
    list_commands = False
    build_native = False
    size_without_split = False

    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("--help", "-h"):
            raise _usage_request()
        if arg == "--goto":
            index += 1
            if index >= len(args):
                raise TuiUsageError("--goto requires a <file:line:col> value")
            goto_file, goto_line, goto_col = _parse_goto(args[index])
        elif arg == "--diff":
            if index + 2 >= len(args):
                raise TuiUsageError("--diff requires two file paths")
            diff_a = _require_file(args[index + 1])
            diff_b = _require_file(args[index + 2])
            index += 2
        elif arg == "--review":
            review = True
        elif arg == "--split":
            index += 1
            if index >= len(args):
                raise TuiUsageError("--split requires a direction")
            split = args[index]
            if split not in _SPLIT_DIRECTIONS:
                raise TuiUsageError(
                    f"--split must be one of {', '.join(_SPLIT_DIRECTIONS)}"
                )
        elif arg == "--size":
            index += 1
            if index >= len(args):
                raise TuiUsageError("--size requires a fraction")
            try:
                split_size = float(args[index])
            except ValueError:
                raise TuiUsageError("--size must be a number") from None
            if not 0.2 <= split_size <= 0.95:
                raise TuiUsageError("--size must be between 0.2 and 0.95")
        elif arg == "--theme":
            index += 1
            if index >= len(args):
                raise TuiUsageError("--theme requires a name")
            theme = args[index]
            if theme not in _SUPPORTED_THEMES:
                raise TuiUsageError(
                    f"unsupported theme {theme!r}; supported: {', '.join(_SUPPORTED_THEMES)}"
                )
        elif arg == "--timing":
            timing = True
        elif arg == "--shortcut-setup":
            shortcut_setup = True
        elif arg == "--list-commands":
            list_commands = True
        elif arg == "--build":
            build_native = True
        elif arg == "--ssh":
            raise TuiUsageError(
                "fcc-tui does not support --ssh: the Admin client only connects "
                "to loopback hosts, so a remote session cannot be honored"
            )
        elif arg in ("--install-extension", "--uninstall-extension"):
            raise TuiUsageError(
                f"{arg} is not supported: FCC manages providers and models, "
                "not VS Code extensions; use the Providers page for custom "
                "OpenAI-compatible endpoints"
            )
        elif arg.startswith("-"):
            raise TuiUsageError(f"unrecognized argument: {arg}")
        else:
            if workspace is not None:
                raise TuiUsageError("fcc-tui accepts at most one workspace path")
            workspace = _require_workspace(arg)
        index += 1

    if split_size is not None and split is None:
        size_without_split = True
    if size_without_split:
        raise TuiUsageError("--size requires --split")

    notice_parts: list[str] = []
    if workspace is not None:
        notice_parts.append(f"Workspace: {workspace}")
    if goto_file is not None:
        notice_parts.append(f"Goto: {goto_file}:{goto_line}:{goto_col}")
    if diff_a is not None and diff_b is not None:
        notice_parts.append(f"Diff: {diff_a.name} ↔ {diff_b.name}")
    if review:
        notice_parts.append("Review: git status snapshot shown before attach")
    if theme != "dark":
        notice_parts.append(f"Theme: {theme}")

    return TuiOptions(
        workspace=workspace,
        goto_file=goto_file,
        goto_line=goto_line,
        goto_col=goto_col,
        diff_a=diff_a,
        diff_b=diff_b,
        review=review,
        split=split,
        split_size=split_size,
        theme=theme,
        timing=timing,
        shortcut_setup=shortcut_setup,
        list_commands=list_commands,
        build_native=build_native,
        notice_parts=tuple(notice_parts),
    )


class _UsageRequest(Exception):
    """Internal signal for `--help` so callers print usage with exit 0."""


def _usage_request() -> _UsageRequest:
    return _UsageRequest(_TUI_USAGE)


def _require_workspace(raw: str) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.exists():
        raise TuiUsageError(f"workspace path does not exist: {raw}")
    # Files pass through; main() roots the control center at the parent and
    # opens the file only for explicit CLI preview compatibility.
    return candidate.resolve()


def _require_file(raw: str) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_file():
        raise TuiUsageError(f"file does not exist: {raw}")
    return candidate.resolve()


def _parse_goto(raw: str) -> tuple[Path, int, int]:
    parts = raw.rsplit(":", 2)
    if len(parts) != 3:
        raise TuiUsageError("--goto must look like <file:line:col>")
    file_raw, line_raw, col_raw = parts
    try:
        line = int(line_raw)
        col = int(col_raw)
    except ValueError:
        raise TuiUsageError("--goto line and column must be integers") from None
    if line < 1 or col < 1:
        raise TuiUsageError("--goto line and column start at 1")
    return _require_file(file_raw), line, col


def render_diff_preview(
    path_a: Path, path_b: Path, *, limit: int = 120
) -> tuple[str, ...]:
    """Render a bounded unified diff preview between two files."""

    lines_a = path_a.read_text(encoding="utf-8", errors="replace").splitlines()
    lines_b = path_b.read_text(encoding="utf-8", errors="replace").splitlines()
    diff = tuple(
        difflib.unified_diff(
            lines_a,
            lines_b,
            fromfile=str(path_a),
            tofile=str(path_b),
            lineterm="",
        )
    )
    if len(diff) > limit:
        return (*diff[:limit], f"… truncated to {limit} lines")
    return diff


def run_git_snapshot(workspace: Path, *, limit: int = 30) -> tuple[str, ...]:
    """Return a bounded `git status` snapshot for `--review`."""

    root = workspace if workspace.is_dir() else workspace.parent
    branch = _run_git(["branch", "--show-current"], cwd=root)
    status = _run_git(["status", "--short"], cwd=root)
    lines = [f"branch: {branch.strip() or '(detached)'}"]
    lines.extend(status.splitlines())
    if len(lines) > limit + 1:
        return (*lines[: limit + 1], f"… truncated to {limit} status lines")
    return tuple(lines)


def _run_git(args: list[str], *, cwd: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TuiUsageError(f"git {' '.join(args)} failed: {exc}") from None
    if completed.returncode != 0:
        raise TuiUsageError(
            f"not a git checkout (or git failed): {cwd} "
            f"({completed.stderr.strip() or 'git exited nonzero'})"
        )
    return completed.stdout


def split_hint(direction: str, size: float | None) -> str:
    """Describe how to open the control center in a multiplexer split."""

    fraction = size if size is not None else 0.5
    if os.environ.get("TMUX"):
        target = {"right": "-h", "left": "-h -b", "up": "-v -b", "down": "-v"}[
            direction
        ]
        return (
            f"tmux split-window {target} -p {round(fraction * 100)} fcc-tui "
            f"# run this yourself; fcc-tui never splits your terminal itself"
        )
    raise TuiUsageError(
        "--split needs a terminal multiplexer and only tmux is recognized "
        "(TMUX is unset); open a second pane manually and run fcc-tui there"
    )


def detect_terminal_kind(environ: Mapping[str, str] | None = None) -> str:
    """Identify the enclosing terminal from standard environment markers."""

    env = environ if environ is not None else os.environ
    if env.get("KITTY_WINDOW_ID") or env.get("TERM") == "xterm-kitty":
        return "kitty"
    if env.get("GHOSTTY_RESOURCES_DIR") or env.get("TERM_PROGRAM") == "ghostty":
        return "ghostty"
    if env.get("ITERM_SESSION_ID") or env.get("TERM_PROGRAM") == "iTerm.app":
        return "iterm2"
    if env.get("VSCODE_INJECTION") or env.get("TERM_PROGRAM") == "vscode":
        return "vscode"
    if env.get("TMUX"):
        return "tmux"
    return "unknown"


def shortcut_conflicts(
    environ: Mapping[str, str] | None = None,
) -> tuple[tuple[str, str, str], ...]:
    """Return (TUI binding, terminal behavior, remediation) rows."""

    kind = detect_terminal_kind(environ)
    rows: list[tuple[str, str, str]] = [
        (
            "Ctrl+K palette",
            "Kitty keyboard protocol may report it as CSI-u; Ghostty/VS Code may bind it",
            "keep the TUI binding and clear the terminal-level Ctrl+K shortcut",
        ),
        (
            "Ctrl+P palette",
            "shell reverse-search and tmux clients often claim Ctrl+P/Ctrl+R neighbours",
            "use Ctrl+K inside the TUI or rebind the terminal action",
        ),
        (
            "Ctrl+C quit",
            "terminals send SIGINT on Ctrl+C outside raw mode",
            "the TUI enables raw mode while focused, so no change is needed",
        ),
        (
            "Mouse clicks",
            "tmux captures mouse events unless mouse mode is on",
            "set `set -g mouse on` in tmux.conf for clickable rows and buttons",
        ),
    ]
    if kind == "unknown":
        return (
            *rows,
            (
                "Terminal detection",
                "no Kitty/Ghostty/iTerm2/VS Code/tmux marker was found",
                "image previews stay metadata-card-only; the TUI itself is unaffected",
            ),
        )
    return tuple(rows)


def render_shortcut_setup(environ: Mapping[str, str] | None = None) -> str:
    """Render the `--shortcut-setup` conflict wizard output."""

    kind = detect_terminal_kind(environ)
    lines = [f"Detected terminal: {kind}", ""]
    for binding, behavior, remediation in shortcut_conflicts(environ):
        lines.append(f"TUI binding : {binding}")
        lines.append(f"  terminal  : {behavior}")
        lines.append(f"  fix       : {remediation}")
    return "\n".join(lines)


def tui_notice(options: TuiOptions) -> str | None:
    """Compose the `--notice` string for the native binary, if any."""

    if not options.notice_parts:
        return None
    notice = " · ".join(options.notice_parts)
    return notice if len(notice) <= 500 else f"{notice[:499]}…"


def native_manifest_path() -> Path:
    """Return the packaged Cargo manifest for the native control center."""

    return Path(__file__).resolve().parents[1] / "native_tui" / "Cargo.toml"


def native_control_command(
    settings: Settings,
    *,
    notice: str | None = None,
    workspace: Path | None = None,
    open: Sequence[Path] = (),
    line: int | None = None,
    launch_args: Sequence[str] = (),
    launch_cwd: Path | None = None,
    launch_danger: bool = False,
) -> tuple[str, ...]:
    """Resolve the native binary or a source-backed Cargo launch command."""

    args = ["--base-url", local_proxy_root_url(settings)]
    if notice:
        args.extend(("--notice", notice))
    if workspace is not None:
        args.extend(("--workspace", str(workspace)))
    for path in open:
        args.extend(("--open", str(path)))
    if line is not None:
        args.extend(("--line", str(line)))
    for launch_arg in launch_args:
        args.extend(("--launch-arg", launch_arg))
    if launch_cwd is not None:
        args.extend(("--launch-cwd", str(launch_cwd)))
    if launch_danger:
        args.append("--launch-danger")

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


def native_binary_install_path() -> Path:
    """Return where a prebuilt control-center binary belongs on PATH."""

    configured = os.environ.get(_NATIVE_BINARY_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    bin_home = os.environ.get("XDG_BIN_HOME", "").strip()
    if bin_home:
        return Path(bin_home).expanduser() / _BINARY_NAME
    return Path.home() / ".local" / "bin" / _BINARY_NAME


def build_native_binary() -> Path:
    """Compile the release control center and install it on PATH.

    The launcher prefers an on-PATH binary over a source-backed `cargo run`,
    so installing once keeps every later `fcc-server`/`fcc-tui` attach fast.
    """

    cargo = shutil.which("cargo")
    if cargo is None:
        raise TuiUsageError("cargo is not on PATH; cannot build the native TUI")
    manifest = native_manifest_path()
    if not manifest.is_file():
        raise TuiUsageError(f"native manifest is missing: {manifest}")
    completed = subprocess.run(
        [cargo, "build", "--release", "--manifest-path", str(manifest)],
        check=False,
    )
    if completed.returncode != 0:
        raise TuiUsageError(
            f"cargo build --release failed with status {completed.returncode}"
        )
    built = manifest.parent / "target" / "release" / _BINARY_NAME
    if not built.is_file():
        raise TuiUsageError(f"expected release binary is missing: {built}")
    target = native_binary_install_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, target)
    return target


def run_native_control_center(
    settings: Settings,
    *,
    notice: str | None = None,
    workspace: Path | None = None,
    open: Sequence[Path] = (),
    line: int | None = None,
    launch_args: Sequence[str] = (),
    launch_cwd: Path | None = None,
    launch_danger: bool = False,
) -> None:
    """Run the native control center in the foreground."""

    command = native_control_command(
        settings,
        notice=notice,
        workspace=workspace,
        open=open,
        line=line,
        launch_args=launch_args,
        launch_cwd=launch_cwd,
        launch_danger=launch_danger,
    )
    completed = subprocess.run(command, check=False)
    if completed.returncode not in {0, 130}:
        raise RuntimeError(
            "Native AgentSwitchboard control center exited with status "
            f"{completed.returncode}."
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Attach the native TUI to an already-running local FCC server."""

    raw = tuple(sys.argv[1:] if argv is None else argv)
    started = time.perf_counter()
    try:
        options = parse_tui_argv(raw)
    except _UsageRequest as request:
        print(str(request.args[0]), file=sys.stdout)
        return 0
    except TuiUsageError as exc:
        print(f"fcc-tui: {exc}", file=sys.stderr)
        print(f"Usage: {_TUI_USAGE}", file=sys.stderr)
        return 2
    parsed_ms = (time.perf_counter() - started) * 1000

    if options.build_native:
        try:
            installed = build_native_binary()
        except TuiUsageError as exc:
            print(f"fcc-tui: {exc}", file=sys.stderr)
            return 2
        print(f"installed {installed}")
        return 0

    if options.list_commands:
        print("\n".join(PALETTE_COMMANDS))
        return 0

    if options.shortcut_setup:
        print(render_shortcut_setup())
        return 0

    from free_claude_code.cli import commands

    if options.diff_a is not None and options.diff_b is not None:
        for line in render_diff_preview(options.diff_a, options.diff_b):
            print(line)

    if options.split is not None:
        try:
            print(split_hint(options.split, options.split_size))
        except TuiUsageError as exc:
            print(f"fcc-tui: {exc}", file=sys.stderr)
            return 2

    workspace = options.workspace
    open_files = [options.goto_file] if options.goto_file is not None else []
    if workspace is not None and workspace.is_file():
        # A positional file becomes an editor tab rooted at its parent.
        open_files.insert(0, workspace)
        workspace = workspace.parent
    if workspace is None and options.goto_file is not None:
        workspace = options.goto_file.parent
    if options.review:
        try:
            for line in run_git_snapshot(workspace or Path.cwd()):
                print(line)
        except TuiUsageError as exc:
            print(f"fcc-tui: {exc}", file=sys.stderr)
            return 2

    settings = commands.load_server_settings()
    settings_ms = (time.perf_counter() - started) * 1000 - parsed_ms
    run_native_control_center(
        settings,
        notice=tui_notice(options),
        workspace=workspace,
        open=open_files,
        line=options.goto_line,
    )
    if options.timing:
        total_ms = (time.perf_counter() - started) * 1000
        print(
            f"fcc-tui timing: parse={parsed_ms:.1f}ms "
            f"settings={settings_ms:.1f}ms total={total_ms:.1f}ms",
            file=sys.stderr,
        )
    return 0
