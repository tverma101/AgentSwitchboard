"""Claude Code CLI characterization helpers for provider smoke matrices."""

import errno
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from free_claude_code.cli.claude_env import build_claude_proxy_env
from free_claude_code.core.version import package_version
from smoke.lib.child_process import run_captured_text
from smoke.lib.config import ProviderModel, SmokeConfig, redacted
from smoke.lib.server import RunningServer

REGRESSION_CLASSIFICATIONS = frozenset({"harness_bug", "product_failure"})

_HTTP_REGRESSION_PATTERNS = (
    r'POST /v1/messages[^"\n]* HTTP/1\.1" 4(?!01|03|04|08|09)\d\d',
    r'POST /v1/messages[^"\n]* HTTP/1\.1" 5\d\d',
)
_UPSTREAM_UNAVAILABLE_MARKERS = (
    "upstream_unavailable",
    "readtimeout",
    "connecterror",
    "connection refused",
    "timed out",
    "rate limit",
    "overloaded",
    "capacity",
    "upstream provider",
    "provider api request failed",
    "httpstatuserror",
)
_HTTP_429_PATTERNS = (
    r'HTTP/1\.[01]" 429\b',
    r"\bHTTP/1\.[01] 429\b",
    r"\bstatus_code=429\b",
    r"\bstatus[=:]\s*429\b",
    r"\b429 Too Many Requests\b",
)
_MISSING_ENV_MARKERS = (
    "api key",
    "not logged in",
    "authentication",
    "permission denied",
)
_EMPTY_MCP_CONFIG = '{"mcpServers":{}}'
CLAUDE_REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CLAUDE_REASONING_EFFORT_OPTIONS = CLAUDE_REASONING_EFFORTS
_BACKGROUND_SESSION_ID_PATTERN = re.compile(
    r"backgrounded\s+.*?\b([0-9a-f]{8})\b", re.IGNORECASE | re.DOTALL
)
_SUBAGENT_SYSTEM_PROMPT = (
    "You are a deterministic smoke-test coordinator. Use Agent when asked to "
    "use a subagent."
)


@dataclass(frozen=True, slots=True)
class ClaudeCliRun:
    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False
    completion_path_observed: bool = False
    requested_context_tokens: int | None = None
    effective_context_tokens: int | None = None

    @property
    def combined_output(self) -> str:
        return f"{self.stdout}\n{self.stderr}"


@dataclass(frozen=True, slots=True)
class CliMatrixOutcome:
    model: str
    full_model: str
    source: str
    feature: str
    outcome: str
    classification: str
    duration_s: float
    cli_returncode: int | None
    token_evidence: dict[str, Any]
    request_count: int
    log_path: str
    stdout_excerpt: str
    stderr_excerpt: str
    log_excerpt: str


def run_claude_cli(
    *,
    claude_bin: str,
    server: RunningServer,
    config: SmokeConfig,
    cwd: Path,
    prompt: str,
    tools: str | None,
    bare: bool = True,
    pre_tool_args: tuple[str, ...] = (),
    extra_args: tuple[str, ...] = (),
    session_id: str | None = None,
    resume_session_id: str | None = None,
    no_session_persistence: bool = True,
    context_cap_tokens: int | None = None,
    prompt_in_stdin: bool = False,
    env_overrides: Mapping[str, str] | None = None,
) -> ClaudeCliRun:
    """Run Claude Code CLI against the local smoke proxy."""
    cwd.mkdir(parents=True, exist_ok=True)

    cmd = list(
        _build_claude_cli_command(
            claude_bin=claude_bin,
            prompt=prompt,
            tools=tools,
            bare=bare,
            pre_tool_args=pre_tool_args,
            extra_args=extra_args,
            session_id=session_id,
            resume_session_id=resume_session_id,
            no_session_persistence=no_session_persistence,
            prompt_in_stdin=prompt_in_stdin,
        )
    )

    env, effective_context_tokens = _build_claude_cli_env(
        server=server,
        config=config,
        context_cap_tokens=context_cap_tokens,
        env_overrides=env_overrides,
    )

    started = time.monotonic()
    try:
        result = run_captured_text(
            cmd,
            cwd=cwd,
            env=env,
            input_text=prompt if prompt_in_stdin else None,
            timeout=config.timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return ClaudeCliRun(
            command=tuple(cmd),
            returncode=None,
            stdout=_coerce_timeout_text(exc.stdout),
            stderr=_coerce_timeout_text(exc.stderr),
            duration_s=time.monotonic() - started,
            timed_out=True,
            requested_context_tokens=context_cap_tokens,
            effective_context_tokens=effective_context_tokens,
        )

    return ClaudeCliRun(
        command=tuple(cmd),
        returncode=result.returncode,
        stdout=_coerce_timeout_text(result.stdout),
        stderr=_coerce_timeout_text(result.stderr),
        duration_s=time.monotonic() - started,
        requested_context_tokens=context_cap_tokens,
        effective_context_tokens=effective_context_tokens,
    )


def _build_claude_cli_env(
    *,
    server: RunningServer,
    config: SmokeConfig,
    context_cap_tokens: int | None,
    env_overrides: Mapping[str, str] | None,
) -> tuple[dict[str, str], int]:
    """Build the exact environment for foreground and attached CLI sessions."""

    base_env = os.environ.copy()
    if env_overrides:
        base_env.update(env_overrides)
    if context_cap_tokens is not None:
        base_env["FCC_CLAUDE_CONTEXT_TOKENS"] = str(context_cap_tokens)
    env = build_claude_proxy_env(
        proxy_root_url=server.base_url,
        auth_token=config.settings.anthropic_auth_token,
        base_env=base_env,
    )
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env, int(env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"])


def _extract_background_session_id(run: ClaudeCliRun) -> str | None:
    """Return the short handle printed by Claude's ``--bg`` launcher."""

    match = _BACKGROUND_SESSION_ID_PATTERN.search(run.combined_output)
    return match.group(1) if match else None


def _run_attached_claude_cli(
    *,
    claude_bin: str,
    session_id: str,
    server: RunningServer,
    config: SmokeConfig,
    cwd: Path,
    prompt: str,
    completion_path: Path,
    log_offset: int,
    env_overrides: Mapping[str, str] | None,
) -> ClaudeCliRun:
    """Attach to a background session through a bounded terminal PTY."""

    attach_bin = _native_attach_binary(claude_bin)
    command = (attach_bin, "attach", session_id)
    started = time.monotonic()
    env, effective_context_tokens = _build_claude_cli_env(
        server=server,
        config=config,
        context_cap_tokens=None,
        env_overrides=env_overrides,
    )
    env["CLAUDE_AX_SCREEN_READER"] = "1"
    if sys.platform == "win32":
        return ClaudeCliRun(
            command=command,
            returncode=None,
            stdout="",
            stderr="background attach smoke requires a POSIX PTY",
            duration_s=time.monotonic() - started,
            timed_out=True,
            effective_context_tokens=effective_context_tokens,
        )

    import pty

    master_fd, slave_fd = pty.openpty()
    pty_command = (
        "script",
        "-q",
        "/dev/null",
        *_build_attached_claude_command(
            claude_bin=attach_bin,
            session_id=session_id,
        ),
    )
    try:
        process = subprocess.Popen(
            list(pty_command),
            cwd=cwd,
            env=env,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        with suppress(OSError):
            os.close(master_fd)
        with suppress(OSError):
            os.close(slave_fd)
        return ClaudeCliRun(
            command=command,
            returncode=None,
            stdout="",
            stderr=f"{type(exc).__name__}: {exc}",
            duration_s=time.monotonic() - started,
            timed_out=False,
            effective_context_tokens=effective_context_tokens,
        )
    os.close(slave_fd)
    os.set_blocking(master_fd, False)
    output = bytearray()
    prompt_typed = False
    prompt_sent = False
    trust_confirmed = False
    input_ready_at: float | None = None
    prompt_submit_attempts = 0
    prompt_submitted_at: float | None = None
    completion_observed_at: float | None = None
    provider_completion_observed_at: float | None = None
    deadline = started + config.timeout_s
    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            if not prompt_sent:
                decoded = output.decode("utf-8", errors="replace")
                trust_prompt = (
                    "Quick safety check" in decoded or "Security guide" in decoded
                )
                if trust_prompt and not trust_confirmed:
                    if input_ready_at is None:
                        input_ready_at = now
                    elif now - input_ready_at >= 0.5:
                        # Native attach normally paints the numbered menu.  A
                        # screen-reader prompt, when present in a future CLI,
                        # uses y/n instead; both answers go through the raw
                        # PTY after the menu has had time to enable input.
                        os.write(
                            master_fd,
                            b"y\r" if "Enter y/n:" in decoded else b"1\r",
                        )
                        trust_confirmed = True
                        input_ready_at = None
                    continue
                if not prompt_typed:
                    ready = _attached_prompt_ready(decoded)
                    suggestion_visible = _attached_prompt_suggestion_visible(decoded)
                    if ready or suggestion_visible:
                        if input_ready_at is None:
                            input_ready_at = now
                        elif now - input_ready_at >= (3.0 if ready else 6.0):
                            os.write(master_fd, prompt.encode("utf-8"))
                            prompt_typed = True
                            input_ready_at = now
                    else:
                        input_ready_at = None
                elif input_ready_at is not None and now - input_ready_at >= 1.0:
                    os.write(master_fd, b"\r")
                    prompt_sent = True
                    prompt_submit_attempts = 1
                    prompt_submitted_at = now
            if (
                prompt_sent
                and prompt_submit_attempts == 1
                and prompt_submitted_at is not None
                and now - prompt_submitted_at >= 1.5
                and '"http_path": "/v1/messages"'
                not in read_log_delta(server.log_path, log_offset)
            ):
                # Some Claude terminal renderers expose Return as LF rather
                # than CR.  Retry once only when the proxy has not observed
                # the submitted turn, preventing duplicate user messages.
                os.write(master_fd, b"\n")
                prompt_submit_attempts = 2
            if prompt_sent and completion_path.is_file():
                if completion_observed_at is None:
                    completion_observed_at = now
                else:
                    provider_response_count = read_log_delta(
                        server.log_path, log_offset
                    ).count('"event": "provider.response.completed"')
                    if provider_response_count >= 2:
                        if provider_completion_observed_at is None:
                            provider_completion_observed_at = now
                        elif now - provider_completion_observed_at >= 2.0:
                            break
                    elif now - completion_observed_at >= 12.0:
                        break

            wait_seconds = min(0.25, max(0.0, deadline - now))
            readable, _, _ = select.select([master_fd], [], [], wait_seconds)
            if not readable:
                continue
            try:
                chunk = os.read(master_fd, 16_384)
            except OSError as exc:
                if exc.errno in {errno.EIO, errno.EBADF}:
                    break
                raise
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > 24_000:
                del output[:-24_000]
    finally:
        _terminate_pty_process(process)
        with suppress(OSError):
            os.close(master_fd)

    text = output.decode("utf-8", errors="replace")
    return ClaudeCliRun(
        command=command,
        returncode=0 if completion_path.is_file() else process.returncode,
        stdout=text,
        stderr="",
        duration_s=time.monotonic() - started,
        timed_out=not completion_path.is_file(),
        completion_path_observed=completion_path.is_file(),
        effective_context_tokens=effective_context_tokens,
    )


def _build_attached_claude_command(
    *, claude_bin: str, session_id: str
) -> tuple[str, ...]:
    """Build the terminal-only command used to attach to a background session."""

    return (claude_bin, "attach", session_id)


def _native_attach_binary(claude_bin: str) -> str:
    """Use Claude's native command parser for ``attach`` subcommands."""

    if Path(claude_bin).name == "fcc-claude":
        return shutil.which("claude") or claude_bin
    return claude_bin


def _attached_prompt_ready(output: str) -> bool:
    """Return whether Claude has painted its interactive input prompt."""

    if "ctrl+g" in output.casefold() and "Try" in output and chr(0x276F) in output:
        return True
    return bool(re.search(r"(?:^|[\r\n])\$(?:\s|$)", output))


def _attached_prompt_suggestion_visible(output: str) -> bool:
    """Return whether the standard TUI has painted its prompt suggestion."""

    return "Try" in output and chr(0x276F) in output


def _terminate_pty_process(process: subprocess.Popen[bytes]) -> None:
    """Stop only the attached smoke process group and reap its child."""

    if process.poll() is not None:
        return
    pid = process.pid
    try:
        process_group = os.getpgid(pid)
    except ProcessLookupError:
        return
    try:
        if process_group == pid:
            os.killpg(process_group, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        try:
            if process_group == pid:
                os.killpg(process_group, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=1.0)


def _stop_background_session(
    *,
    claude_bin: str,
    session_id: str,
    cwd: Path,
    env: Mapping[str, str],
) -> None:
    """Stop the exact smoke-created background handle after the probe."""

    native_binary = shutil.which("claude") or claude_bin
    try:
        run_captured_text(
            (native_binary, "stop", session_id),
            cwd=cwd,
            env=env,
            timeout=5.0,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return


def _build_claude_cli_command(
    *,
    claude_bin: str,
    prompt: str,
    tools: str | None,
    bare: bool = True,
    pre_tool_args: tuple[str, ...] = (),
    extra_args: tuple[str, ...] = (),
    session_id: str | None = None,
    resume_session_id: str | None = None,
    no_session_persistence: bool = True,
    prompt_in_stdin: bool = False,
) -> tuple[str, ...]:
    cmd: list[str] = [claude_bin]
    background = "--bg" in extra_args or "--background" in extra_args
    if bare:
        cmd.append("--bare")
    if resume_session_id:
        cmd.extend(["--resume", resume_session_id])
    if session_id:
        cmd.extend(["--session-id", session_id])
    if background:
        # Background sessions are interactive Claude processes.  The stream-json,
        # partial-message, and verbose flags below are print-mode options; passing
        # them to --bg can return a handle and then terminate the daemon before it
        # inherits the FCC request path.
        cmd.extend(
            [
                "--permission-mode",
                "default",
                "--model",
                "sonnet",
            ]
        )
    else:
        cmd.extend(
            [
                "--output-format",
                "stream-json",
                "--include-partial-messages",
                "--verbose",
                "--permission-mode",
                "default",
                "--model",
                "sonnet",
            ]
        )
    if no_session_persistence:
        cmd.append("--no-session-persistence")
    cmd.extend(pre_tool_args)
    if tools is not None:
        cmd.extend(["--tools", tools])
        if tools:
            cmd.extend(["--allowedTools", tools])
    cmd.extend(extra_args)
    if background:
        # Claude's background-session manager rejects --print/-p because the
        # resulting session would not be attachable through `claude agents`.
        cmd.append(prompt)
    else:
        cmd.extend(["-p"] if prompt_in_stdin else ["-p", prompt])
    return tuple(cmd)


def run_cli_feature_probes(
    *,
    claude_bin: str,
    server: RunningServer,
    smoke_config: SmokeConfig,
    provider_model: ProviderModel,
    model_dir: Path,
    marker_prefix: str,
) -> list[CliMatrixOutcome]:
    return [
        _basic_text(
            claude_bin, server, smoke_config, provider_model, model_dir, marker_prefix
        ),
        _thinking(
            claude_bin, server, smoke_config, provider_model, model_dir, marker_prefix
        ),
        _tool_use_roundtrip(
            claude_bin, server, smoke_config, provider_model, model_dir, marker_prefix
        ),
        _interleaved_thinking_tool(
            claude_bin, server, smoke_config, provider_model, model_dir, marker_prefix
        ),
        _subagent_task(
            claude_bin, server, smoke_config, provider_model, model_dir, marker_prefix
        ),
        _compact_command(
            claude_bin, server, smoke_config, provider_model, model_dir, marker_prefix
        ),
    ]


def run_reasoning_effort_matrix(
    *,
    claude_bin: str,
    server: RunningServer,
    smoke_config: SmokeConfig,
    provider_model: ProviderModel,
    model_dir: Path,
    marker_prefix: str,
    efforts: tuple[str, ...] = CLAUDE_REASONING_EFFORTS,
) -> list[CliMatrixOutcome]:
    """Run the installed Claude CLI through selected effort levels."""
    outcomes: list[CliMatrixOutcome] = []
    unknown = sorted(set(efforts) - set(CLAUDE_REASONING_EFFORT_OPTIONS))
    if unknown:
        raise ValueError(
            f"unsupported Claude reasoning effort(s): {', '.join(unknown)}"
        )
    for effort in efforts:
        marker = _marker(marker_prefix, f"REASONING_{effort.upper()}")
        outcomes.append(
            _run_probe(
                claude_bin=claude_bin,
                server=server,
                smoke_config=smoke_config,
                provider_model=provider_model,
                workspace=model_dir / f"reasoning_{effort}",
                feature=f"reasoning_{effort}",
                marker=marker,
                prompt=f"Reply with exactly {marker} and no other text.",
                tools="",
                extra_args=("--effort", effort),
            )
        )
    return outcomes


def run_subagent_probe(
    *,
    claude_bin: str,
    server: RunningServer,
    smoke_config: SmokeConfig,
    provider_model: ProviderModel,
    model_dir: Path,
    marker_prefix: str,
) -> CliMatrixOutcome:
    """Run the strict foreground Agent/subagent tool probe."""
    return _subagent_task(
        claude_bin,
        server,
        smoke_config,
        provider_model,
        model_dir,
        marker_prefix,
    )


def run_background_subagent_probe(
    *,
    claude_bin: str,
    server: RunningServer,
    smoke_config: SmokeConfig,
    provider_model: ProviderModel,
    model_dir: Path,
    marker_prefix: str,
) -> CliMatrixOutcome:
    """Run one top-level Claude background-session tool probe."""
    return _background_session_probe(
        claude_bin=claude_bin,
        server=server,
        smoke_config=smoke_config,
        provider_model=provider_model,
        model_dir=model_dir,
        marker_prefix=marker_prefix,
    )


def _background_session_probe(
    *,
    claude_bin: str,
    server: RunningServer,
    smoke_config: SmokeConfig,
    provider_model: ProviderModel,
    model_dir: Path,
    marker_prefix: str,
) -> CliMatrixOutcome:
    """Start Claude with ``--bg`` and wait for one bounded tool marker."""
    marker = _marker(marker_prefix, "BACKGROUND")
    workspace = model_dir / "background_session"
    workspace.mkdir(parents=True, exist_ok=True)
    marker_path = workspace / "background-marker.txt"
    marker_path.unlink(missing_ok=True)
    isolated_cli_args = (
        "--setting-sources",
        "local",
        "--strict-mcp-config",
        "--mcp-config",
        _EMPTY_MCP_CONFIG,
        "--name",
        "fcc-background-smoke",
        "--system-prompt",
        _SUBAGENT_SYSTEM_PROMPT,
    )
    launcher_env = {
        "HOST": "127.0.0.1",
        "PORT": str(server.port),
        "MODEL": provider_model.full_model,
        # Claude's optional terminal-title classifier sends a separate
        # reasoning-off request.  Keep this workload focused on the
        # user-visible background session and avoid an unrelated auxiliary
        # request that OpenCode Go does not need to serve.
        "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1",
        "CLAUDE_CODE_ENABLE_AWAY_SUMMARY": "0",
    }
    offset = read_log_offset(server.log_path)
    run = run_claude_cli(
        claude_bin=claude_bin,
        server=server,
        config=smoke_config,
        cwd=workspace,
        prompt=(
            "Use Bash exactly once to run `printf %s "
            f"{marker} > background-marker.txt`. After the command succeeds, stop."
        ),
        tools="Bash",
        bare=False,
        pre_tool_args=isolated_cli_args,
        extra_args=("--bg",),
        no_session_persistence=False,
        env_overrides=launcher_env,
    )
    session_id = _extract_background_session_id(run)
    if session_id:
        try:
            attached_run = _run_attached_claude_cli(
                claude_bin=claude_bin,
                session_id=session_id,
                server=server,
                config=smoke_config,
                cwd=workspace,
                prompt=(
                    "Use Bash exactly once to run `printf %s "
                    f"{marker} > background-marker.txt`. After the command succeeds, stop."
                ),
                completion_path=marker_path,
                log_offset=offset,
                env_overrides=launcher_env,
            )
            run = replace(
                run,
                command=run.command + attached_run.command,
                returncode=attached_run.returncode,
                stdout=f"{run.stdout}\n{attached_run.stdout}",
                stderr=f"{run.stderr}\n{attached_run.stderr}",
                duration_s=run.duration_s + attached_run.duration_s,
                timed_out=attached_run.timed_out,
                completion_path_observed=attached_run.completion_path_observed,
                effective_context_tokens=attached_run.effective_context_tokens,
            )
        finally:
            stop_env, _ = _build_claude_cli_env(
                server=server,
                config=smoke_config,
                context_cap_tokens=None,
                env_overrides=launcher_env,
            )
            _stop_background_session(
                claude_bin=claude_bin,
                session_id=session_id,
                cwd=workspace,
                env=stop_env,
            )
    # The PTY helper already owns the full bounded wait.  A second full wait
    # here would turn one failed attach into an unbounded-looking 90-second
    # smoke and hide the attach transcript needed for diagnosis.
    deadline = time.monotonic() + (smoke_config.timeout_s if not run.timed_out else 0.0)
    while not marker_path.is_file() and time.monotonic() < deadline:
        time.sleep(0.5)
    marker_seen = (
        marker_path.is_file()
        and marker_path.read_text(encoding="utf-8", errors="replace").strip() == marker
    )
    run = replace(
        run,
        stdout=f"{run.stdout}\n{marker}" if marker_seen else run.stdout,
        timed_out=not marker_seen,
        completion_path_observed=marker_seen,
    )
    log_delta = read_log_delta(server.log_path, offset)
    return make_outcome(
        model=provider_model.model_name,
        full_model=provider_model.full_model,
        source=provider_model.source,
        feature="background_session_tool_task",
        marker=marker,
        run=run,
        log_delta=log_delta,
        log_path=server.log_path,
        requires_tool_result=True,
        requires_background_task=True,
    )


def run_auto_compact_probe(
    *,
    claude_bin: str,
    server: RunningServer,
    smoke_config: SmokeConfig,
    provider_model: ProviderModel,
    model_dir: Path,
    marker_prefix: str,
) -> CliMatrixOutcome:
    """Run one real automatic-compaction and post-boundary tool probe.

    The seed turns intentionally use separate Claude invocations that resume
    one persisted session.  No ``/compact`` command is sent; the final turn
    must observe Claude's automatic boundary and then complete a Bash tool
    round trip on the resumed session.
    """
    marker = _marker(marker_prefix, "AUTO_COMPACT")
    continuation_marker = _marker(marker_prefix, "AUTO_COMPACT_CONTINUED")
    workspace = model_dir / "auto_compact_resume"
    session_id = str(uuid.uuid4())
    context_seed = "context " * 7_000
    launcher_env = {
        "HOST": "127.0.0.1",
        "PORT": str(server.port),
        "MODEL": provider_model.full_model,
    }
    isolated_cli_args = (
        "--setting-sources",
        "local",
        "--strict-mcp-config",
        "--mcp-config",
        _EMPTY_MCP_CONFIG,
    )
    offset = read_log_offset(server.log_path)
    seed_prompts = tuple(
        f"Retain the earlier smoke token {marker} and reply with exactly "
        f"{marker}_GROUP_{group} after this bounded context seed.\n"
        f"{context_seed}"
        # Four groups reached only about 30K input tokens on Claude 2.1.228;
        # seven keeps the fixture bounded while crossing the 50K gate.
        for group in range(1, 8)
    )
    seed_runs = [
        run_claude_cli(
            claude_bin=claude_bin,
            server=server,
            config=smoke_config,
            cwd=workspace,
            prompt=prompt,
            tools="",
            bare=False,
            pre_tool_args=isolated_cli_args,
            session_id=session_id if index == 0 else None,
            resume_session_id=session_id if index else None,
            no_session_persistence=False,
            context_cap_tokens=50_000,
            prompt_in_stdin=True,
            env_overrides=launcher_env,
        )
        for index, prompt in enumerate(seed_prompts)
    ]
    continuation_run = run_claude_cli(
        claude_bin=claude_bin,
        server=server,
        config=smoke_config,
        cwd=workspace,
        prompt=(
            f"After automatic compaction, use Bash to run `printf {continuation_marker}`. "
            f"Reply with exactly {continuation_marker} after the tool succeeds."
        ),
        tools="Bash",
        bare=False,
        pre_tool_args=isolated_cli_args,
        resume_session_id=session_id,
        no_session_persistence=False,
        context_cap_tokens=50_000,
        env_overrides=launcher_env,
    )
    runs = [*seed_runs, continuation_run]
    command: list[str] = []
    for item in runs:
        if command:
            command.append("&&")
        command.extend(item.command)
    returncode = next((item.returncode for item in runs if item.returncode != 0), 0)
    log_delta = read_log_delta(server.log_path, offset)
    run = ClaudeCliRun(
        command=tuple(command),
        returncode=returncode,
        stdout="\n".join(item.stdout for item in runs),
        stderr="\n".join(item.stderr for item in runs),
        duration_s=sum(item.duration_s for item in runs),
        timed_out=any(item.timed_out for item in runs),
        requested_context_tokens=50_000,
        effective_context_tokens=50_000,
    )
    return make_outcome(
        model=provider_model.model_name,
        full_model=provider_model.full_model,
        source=provider_model.source,
        feature="auto_compact_resume",
        marker=continuation_marker,
        run=run,
        log_delta=log_delta,
        log_path=server.log_path,
        requires_tool_result=True,
        requires_compact=True,
        requires_auto_compact=True,
        requires_continuation=True,
    )


def read_log_offset(log_path: Path) -> int:
    """Return the current text length of a smoke server log."""
    if not log_path.is_file():
        return 0
    return len(log_path.read_text(encoding="utf-8", errors="replace"))


def read_log_delta(log_path: Path, offset: int) -> str:
    """Return smoke server log text written after ``offset``."""
    if not log_path.is_file():
        return ""
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return text[offset:]


def token_evidence(
    *,
    feature: str,
    marker: str,
    run: ClaudeCliRun,
    log_delta: str,
) -> dict[str, Any]:
    """Collect compact evidence for a CLI feature probe."""
    combined = f"{run.combined_output}\n{log_delta}"
    lower = combined.lower()
    return {
        "feature": feature,
        "marker_present": bool(marker and marker in combined),
        "thinking_delta_count": combined.count("thinking_delta"),
        "tool_use_count": combined.count('"tool_use"')
        + int(
            feature == "background_session_tool_task" and run.completion_path_observed
        ),
        "tool_result_count": combined.count('"tool_result"')
        + int(
            feature == "background_session_tool_task" and run.completion_path_observed
        ),
        "agent_catalog_present": _tool_catalog_has(log_delta, "Agent"),
        "agent_tool_count": _agent_tool_count(combined),
        "agent_result_count": _agent_result_count(combined),
        "task_tool_count": combined.count('"name": "Task"')
        + combined.count('"name":"Task"'),
        "background_flag": "--bg" in run.command or "--background" in run.command,
        "run_in_background_true": _metadata_bool_seen(
            combined, "run_in_background", True
        ),
        "run_in_background_false": "run_in_background" in combined and "false" in lower,
        "compact_boundary": "compact_boundary" in combined,
        "compact_metadata": "compact_metadata" in combined,
        "compact_trigger": _compact_trigger(combined),
        "auto_compact": _compact_trigger(combined) == "auto",
        "compact_result_success": bool(
            re.search(r'"compact_result"\s*:\s*"success"', combined)
        ),
        "reasoning_effort_values": _metadata_values(combined, "reasoning_effort"),
        "requested_context_tokens": run.requested_context_tokens,
        "effective_context_tokens": run.effective_context_tokens,
        "completion_path_observed": run.completion_path_observed,
        "http_422": 'HTTP/1.1" 422' in combined,
        "http_500": bool(re.search(r'HTTP/1\.1" 5\d\d', combined)),
        "timed_out": run.timed_out,
        **_provider_telemetry(log_delta),
    }


def classify_probe(
    *,
    feature: str,
    run: ClaudeCliRun,
    log_delta: str,
    marker: str,
    requires_tool_result: bool = False,
    requires_agent: bool = False,
    requires_task: bool = False,
    requires_compact: bool = False,
    requires_auto_compact: bool = False,
    requires_continuation: bool = False,
    requires_background_task: bool = False,
) -> tuple[str, str]:
    """Classify a probe without failing compatibility characterization failures."""
    combined = f"{run.combined_output}\n{log_delta}"
    lower = combined.lower()

    if _has_proxy_regression(log_delta):
        return "failed", "product_failure"
    if run.returncode != 0 and any(
        marker_text in lower for marker_text in _MISSING_ENV_MARKERS
    ):
        return "skipped", "missing_env"
    if run.timed_out:
        return "failed", "probe_timeout"
    if requires_agent and not _tool_catalog_has(log_delta, "Agent"):
        return "failed", "harness_bug"

    marker_ok = not marker or marker in combined
    tool_ok = not requires_tool_result or (
        '"tool_result"' in combined
        or (requires_background_task and run.completion_path_observed)
    )
    agent_ok = not requires_agent or (
        _agent_tool_count(combined) > 0 and _agent_result_count(combined) > 0
    )
    task_ok = not requires_task or (
        ('"name": "Task"' in combined or '"name":"Task"' in combined)
        and "run_in_background" in combined
        and "false" in lower
    )
    background_task_ok = not requires_background_task or (
        "--bg" in run.command
        or "--background" in run.command
        or _metadata_bool_seen(combined, "run_in_background", True)
    )
    reasoning_effort_ok = True
    if feature.startswith("reasoning_"):
        expected_effort = feature.removeprefix("reasoning_")
        reasoning_effort_ok = _metadata_values(combined, "reasoning_effort") == [
            expected_effort
        ]
    compact_ok = not requires_compact or (
        bool(re.search(r'"compact_result"\s*:\s*"success"', combined))
        and ("compact_boundary" in combined or "compact_metadata" in combined)
    )
    auto_compact_ok = not requires_auto_compact or _compact_trigger(combined) == "auto"
    continuation_ok = not requires_continuation or marker in combined
    cli_ok = run.returncode == 0

    if (
        cli_ok
        and marker_ok
        and tool_ok
        and agent_ok
        and task_ok
        and background_task_ok
        and reasoning_effort_ok
        and compact_ok
        and auto_compact_ok
        and continuation_ok
    ):
        return "passed", "passed"
    if _has_upstream_unavailable_text(combined):
        return "failed", "upstream_unavailable"
    if not _has_proxy_request(log_delta):
        return "failed", "harness_bug"
    return "failed", "model_feature_failure"


def make_outcome(
    *,
    model: str,
    full_model: str,
    source: str,
    feature: str,
    marker: str,
    run: ClaudeCliRun,
    log_delta: str,
    log_path: Path,
    requires_tool_result: bool = False,
    requires_agent: bool = False,
    requires_task: bool = False,
    requires_compact: bool = False,
    requires_auto_compact: bool = False,
    requires_continuation: bool = False,
    requires_background_task: bool = False,
) -> CliMatrixOutcome:
    """Build one report outcome from a CLI run and its server log delta."""
    outcome, classification = classify_probe(
        feature=feature,
        run=run,
        log_delta=log_delta,
        marker=marker,
        requires_tool_result=requires_tool_result,
        requires_agent=requires_agent,
        requires_task=requires_task,
        requires_compact=requires_compact,
        requires_auto_compact=requires_auto_compact,
        requires_continuation=requires_continuation,
        requires_background_task=requires_background_task,
    )
    evidence = token_evidence(
        feature=feature,
        marker=marker,
        run=run,
        log_delta=log_delta,
    )
    return CliMatrixOutcome(
        model=model,
        full_model=full_model,
        source=source,
        feature=feature,
        outcome=outcome,
        classification=classification,
        duration_s=round(run.duration_s, 3),
        cli_returncode=run.returncode,
        token_evidence=evidence,
        request_count=_request_count(log_delta),
        log_path=str(log_path),
        stdout_excerpt=_excerpt(run.stdout),
        stderr_excerpt=_excerpt(run.stderr),
        log_excerpt=_excerpt(log_delta),
    )


def write_matrix_report(
    config: SmokeConfig,
    outcomes: list[CliMatrixOutcome],
    *,
    target: str,
    filename_prefix: str,
) -> Path:
    """Write a Claude CLI compatibility matrix report."""
    config.results_dir.mkdir(parents=True, exist_ok=True)
    path = (
        config.results_dir
        / f"{filename_prefix}-matrix-{config.worker_id}-{int(time.time())}.json"
    )
    payload = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "worker_id": config.worker_id,
        "target": target,
        "harness": {
            "package_version": package_version(),
            "commit_sha": _git_sha(),
        },
        "models": sorted({outcome.full_model for outcome in outcomes}),
        "outcomes": [asdict(outcome) for outcome in outcomes],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def regression_failures(outcomes: list[CliMatrixOutcome]) -> list[str]:
    """Return report lines for classifications that should fail pytest."""
    return [
        f"{outcome.full_model} {outcome.feature}: {outcome.classification}"
        for outcome in outcomes
        if outcome.classification in REGRESSION_CLASSIFICATIONS
    ]


def _basic_text(
    claude_bin: str,
    server: RunningServer,
    smoke_config: SmokeConfig,
    provider_model: ProviderModel,
    model_dir: Path,
    marker_prefix: str,
) -> CliMatrixOutcome:
    marker = _marker(marker_prefix, "BASIC")
    return _run_probe(
        claude_bin=claude_bin,
        server=server,
        smoke_config=smoke_config,
        provider_model=provider_model,
        workspace=model_dir / "basic_text",
        feature="basic_text",
        marker=marker,
        prompt=f"Reply with exactly {marker} and no other text.",
        tools="",
    )


def _thinking(
    claude_bin: str,
    server: RunningServer,
    smoke_config: SmokeConfig,
    provider_model: ProviderModel,
    model_dir: Path,
    marker_prefix: str,
) -> CliMatrixOutcome:
    marker = _marker(marker_prefix, "THINK")
    return _run_probe(
        claude_bin=claude_bin,
        server=server,
        smoke_config=smoke_config,
        provider_model=provider_model,
        workspace=model_dir / "thinking",
        feature="thinking",
        marker=marker,
        prompt=(
            "Think privately about the request, then reply with exactly "
            f"{marker} and no other text."
        ),
        tools="",
        extra_args=("--effort", "high"),
    )


def _tool_use_roundtrip(
    claude_bin: str,
    server: RunningServer,
    smoke_config: SmokeConfig,
    provider_model: ProviderModel,
    model_dir: Path,
    marker_prefix: str,
) -> CliMatrixOutcome:
    marker = _marker(marker_prefix, "TOOL")
    workspace = model_dir / "tool_use_roundtrip"
    (workspace / "smoke-read.txt").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "smoke-read.txt").write_text(marker, encoding="utf-8")
    return _run_probe(
        claude_bin=claude_bin,
        server=server,
        smoke_config=smoke_config,
        provider_model=provider_model,
        workspace=workspace,
        feature="tool_use_roundtrip",
        marker=marker,
        prompt=(
            "Use the Read tool to read smoke-read.txt. Reply with exactly the "
            "secret token from that file and no other text."
        ),
        tools="Read",
        requires_tool_result=True,
    )


def _interleaved_thinking_tool(
    claude_bin: str,
    server: RunningServer,
    smoke_config: SmokeConfig,
    provider_model: ProviderModel,
    model_dir: Path,
    marker_prefix: str,
) -> CliMatrixOutcome:
    marker = _marker(marker_prefix, "INTERLEAVED")
    workspace = model_dir / "interleaved_thinking_tool"
    (workspace / "smoke-interleaved.txt").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "smoke-interleaved.txt").write_text(marker, encoding="utf-8")
    return _run_probe(
        claude_bin=claude_bin,
        server=server,
        smoke_config=smoke_config,
        provider_model=provider_model,
        workspace=workspace,
        feature="interleaved_thinking_tool",
        marker=marker,
        prompt=(
            "Think privately, use Read on smoke-interleaved.txt, then reply with "
            "exactly the secret token from that file and no other text."
        ),
        tools="Read",
        extra_args=("--effort", "high"),
        requires_tool_result=True,
    )


def _subagent_task(
    claude_bin: str,
    server: RunningServer,
    smoke_config: SmokeConfig,
    provider_model: ProviderModel,
    model_dir: Path,
    marker_prefix: str,
) -> CliMatrixOutcome:
    marker = _marker(marker_prefix, "TASK")
    workspace = model_dir / "subagent_task"
    (workspace / "smoke-subagent.txt").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "smoke-subagent.txt").write_text(marker, encoding="utf-8")
    agents = json.dumps(
        {
            "smoke_reader": {
                "description": "Reads one requested file and returns its token.",
                "prompt": (
                    "Read the requested file with Read and return only the token "
                    "inside it."
                ),
                "tools": ["Read"],
                "background": False,
            }
        }
    )
    bare, tools, pre_tool_args, extra_args = _subagent_probe_options(agents)
    return _run_probe(
        claude_bin=claude_bin,
        server=server,
        smoke_config=smoke_config,
        provider_model=provider_model,
        workspace=workspace,
        feature="subagent_task",
        marker=marker,
        prompt=(
            "Use the smoke_reader subagent to read smoke-subagent.txt. After the "
            "first agent result, reply with exactly the token and stop. Do not "
            "call any other tools."
        ),
        tools=tools,
        bare=bare,
        pre_tool_args=pre_tool_args,
        extra_args=extra_args,
        requires_tool_result=True,
        requires_agent=True,
    )


def _subagent_probe_options(
    agents: str,
) -> tuple[bool, str, tuple[str, ...], tuple[str, ...]]:
    return (
        False,
        "Agent,Read",
        (
            "--setting-sources",
            "local",
            "--strict-mcp-config",
            "--mcp-config",
            _EMPTY_MCP_CONFIG,
            "--system-prompt",
            _SUBAGENT_SYSTEM_PROMPT,
        ),
        ("--agents", agents),
    )


def _compact_command(
    claude_bin: str,
    server: RunningServer,
    smoke_config: SmokeConfig,
    provider_model: ProviderModel,
    model_dir: Path,
    marker_prefix: str,
) -> CliMatrixOutcome:
    marker = _marker(marker_prefix, "COMPACT")
    continuation_marker = _marker(marker_prefix, "COMPACT_CONTINUED")
    workspace = model_dir / "compact_command"
    session_id = str(uuid.uuid4())
    context_seed = "context " * 7_000
    offset = read_log_offset(server.log_path)
    seed_prompts = (
        f"Remember this smoke token: {marker}. Reply with exactly {marker} "
        "after retaining the following bounded context seed.\n"
        f"{context_seed}",
        f"Retain the earlier smoke token {marker} and reply with exactly "
        f"{marker}_GROUP_2 after this bounded context seed.\n{context_seed}",
        f"Retain the earlier smoke token {marker} and reply with exactly "
        f"{marker}_GROUP_3 after this bounded context seed.\n{context_seed}",
    )
    seed_runs = [
        run_claude_cli(
            claude_bin=claude_bin,
            server=server,
            config=smoke_config,
            cwd=workspace,
            prompt=prompt,
            tools="",
            session_id=session_id if index == 0 else None,
            resume_session_id=session_id if index else None,
            no_session_persistence=False,
            context_cap_tokens=50_000,
            prompt_in_stdin=True,
        )
        for index, prompt in enumerate(seed_prompts)
    ]
    compact_run = run_claude_cli(
        claude_bin=claude_bin,
        server=server,
        config=smoke_config,
        cwd=workspace,
        prompt=f"/compact preserve {marker}",
        tools="",
        resume_session_id=session_id,
        no_session_persistence=False,
        context_cap_tokens=50_000,
    )
    continuation_run = run_claude_cli(
        claude_bin=claude_bin,
        server=server,
        config=smoke_config,
        cwd=workspace,
        prompt=(
            f"After compaction, reply with exactly {continuation_marker}. "
            f"You preserved the earlier token {marker}."
        ),
        tools="",
        resume_session_id=session_id,
        no_session_persistence=False,
        context_cap_tokens=50_000,
    )
    runs = [*seed_runs, compact_run, continuation_run]
    command: list[str] = []
    for item in runs:
        if command:
            command.append("&&")
        command.extend(item.command)
    returncode = next((item.returncode for item in runs if item.returncode != 0), 0)
    log_delta = read_log_delta(server.log_path, offset)
    run = ClaudeCliRun(
        command=tuple(command),
        returncode=returncode,
        stdout="\n".join(item.stdout for item in runs),
        stderr="\n".join(item.stderr for item in runs),
        duration_s=sum(item.duration_s for item in runs),
        timed_out=any(item.timed_out for item in runs),
        requested_context_tokens=50_000,
        effective_context_tokens=50_000,
    )
    return make_outcome(
        model=provider_model.model_name,
        full_model=provider_model.full_model,
        source=provider_model.source,
        feature="compact_resume",
        marker=continuation_marker,
        run=run,
        log_delta=log_delta,
        log_path=server.log_path,
        requires_compact=True,
        requires_continuation=True,
    )


def _run_probe(
    *,
    claude_bin: str,
    server: RunningServer,
    smoke_config: SmokeConfig,
    provider_model: ProviderModel,
    workspace: Path,
    feature: str,
    marker: str,
    prompt: str,
    tools: str | None,
    bare: bool = True,
    pre_tool_args: tuple[str, ...] = (),
    extra_args: tuple[str, ...] = (),
    requires_tool_result: bool = False,
    requires_agent: bool = False,
    requires_task: bool = False,
    requires_background_task: bool = False,
) -> CliMatrixOutcome:
    offset = read_log_offset(server.log_path)
    run = run_claude_cli(
        claude_bin=claude_bin,
        server=server,
        config=smoke_config,
        cwd=workspace,
        prompt=prompt,
        tools=tools,
        bare=bare,
        pre_tool_args=pre_tool_args,
        extra_args=extra_args,
        env_overrides={
            "HOST": "127.0.0.1",
            "PORT": str(server.port),
            "MODEL": provider_model.full_model,
        },
    )
    log_delta = read_log_delta(server.log_path, offset)
    return make_outcome(
        model=provider_model.model_name,
        full_model=provider_model.full_model,
        source=provider_model.source,
        feature=feature,
        marker=marker,
        run=run,
        log_delta=log_delta,
        log_path=server.log_path,
        requires_tool_result=requires_tool_result,
        requires_agent=requires_agent,
        requires_task=requires_task,
        requires_background_task=requires_background_task,
    )


def _has_proxy_regression(log_delta: str) -> bool:
    if "CREATE_MESSAGE_ERROR" in log_delta:
        return True
    return any(re.search(pattern, log_delta) for pattern in _HTTP_REGRESSION_PATTERNS)


def _compact_trigger(text: str) -> str | None:
    """Return the explicit Claude compaction trigger from a metadata row."""
    for line in text.splitlines():
        if "compact" not in line.casefold():
            continue
        for pattern in (
            r'"trigger"\s*:\s*"(?P<trigger>auto|manual)"',
            r"'trigger'\s*:\s*'(?P<trigger>auto|manual)'",
        ):
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if match:
                return match.group("trigger").lower()
    return None


def _metadata_values(text: str, key: str) -> list[str]:
    """Return redacted string values for one structured trace key."""
    values = re.findall(
        rf"['\"]{re.escape(key)}['\"]\s*:\s*['\"]([^'\"]+)['\"]",
        text,
        flags=re.IGNORECASE,
    )
    return sorted(set(values))


def _metadata_bool_seen(text: str, key: str, expected: bool) -> bool:
    """Return whether a structured metadata key has the expected boolean."""
    value = "true" if expected else "false"
    return bool(
        re.search(
            rf"['\"]{re.escape(key)}['\"]\s*:\s*{value}\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _has_proxy_request(log_delta: str) -> bool:
    return (
        "POST /v1/messages" in log_delta
        or "API_REQUEST:" in log_delta
        or '"event": "free_claude_code.api.request.received"' in log_delta
        or (
            '"http_method": "POST"' in log_delta
            and '"http_path": "/v1/messages"' in log_delta
        )
    )


def _provider_telemetry(log_delta: str) -> dict[str, Any]:
    """Summarize structured provider receipts without retaining request data."""

    records: list[dict[str, Any]] = []
    for line in log_delta.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("event") == (
            "provider.fault_attribution"
        ):
            records.append(value)

    attempts = [
        value["attempt_number"]
        for value in records
        if isinstance(value.get("attempt_number"), int)
        and not isinstance(value["attempt_number"], bool)
    ]
    durations = _non_negative_numeric_values(records, "duration_ms")
    ttfts = _non_negative_numeric_values(records, "time_to_first_token_ms")
    request_hashes = _string_values(records, "request_shape_hash")
    stable_hashes = _string_values(records, "stable_prefix_hash")
    completed = [value for value in records if value.get("outcome") == "completed"]
    return {
        "provider_fault_record_count": len(records),
        "provider_ids": sorted(
            {
                value["provider"]
                for value in records
                if isinstance(value.get("provider"), str)
            }
        ),
        "upstream_protocols": sorted(
            {
                value["protocol"]
                for value in records
                if isinstance(value.get("protocol"), str)
            }
        ),
        "completed_provider_turns": len(completed),
        "upstream_attempts_total": sum(attempts),
        "upstream_attempts_per_completed_turn": (
            sum(attempts) / len(completed) if completed else None
        ),
        "provider_http_error_count": sum(
            value.get("http_status") is not None for value in records
        ),
        "response_completed_event_count": sum(
            value.get("terminal_event") == "response.completed" for value in records
        ),
        "request_shape_hash_count": len(set(request_hashes)),
        "stable_prefix_hash_count": len(set(stable_hashes)),
        "duration_ms": _numeric_summary(durations),
        "time_to_first_token_ms": _numeric_summary(ttfts),
    }


def _non_negative_numeric_values(
    records: list[dict[str, Any]], key: str
) -> list[float]:
    values: list[float] = []
    for record in records:
        value = record.get(key)
        if (
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and value >= 0
        ):
            values.append(float(value))
    return values


def _string_values(records: list[dict[str, Any]], key: str) -> list[str]:
    return [
        value[key]
        for value in records
        if isinstance(value.get(key), str) and value[key]
    ]


def _numeric_summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {"min": min(values), "max": max(values)}


def _tool_catalog_has(log_delta: str, tool_name: str) -> bool:
    catalog = _first_tool_catalog(log_delta)
    return (
        f"'name': '{tool_name}'" in catalog
        or f'"name": "{tool_name}"' in catalog
        or f'"name":"{tool_name}"' in catalog
    )


def _first_tool_catalog(log_delta: str) -> str:
    for line in log_delta.splitlines():
        if "FULL_PAYLOAD" not in line:
            continue
        single_index = line.find("'tools': [")
        double_index = line.find('"tools": [')
        if single_index == -1 and double_index == -1:
            continue
        start = single_index if single_index != -1 else double_index
        end_candidates = [
            index
            for marker in ("'tool_choice'", '"tool_choice"', "'thinking'", '"thinking"')
            if (index := line.find(marker, start)) != -1
        ]
        end = min(end_candidates) if end_candidates else len(line)
        return line[start:end]
    return ""


def _agent_tool_count(text: str) -> int:
    return (
        text.count('"name": "Agent"')
        + text.count('"name":"Agent"')
        + len(
            re.findall(
                r"'type': 'tool_use'[^}\n]+?'name': 'Agent'",
                text,
                flags=re.DOTALL,
            )
        )
    )


def _agent_result_count(text: str) -> int:
    return text.count("agentId:") + text.count('"agentId"') + text.count("'agentId'")


def _has_upstream_unavailable_text(text: str) -> bool:
    lower = text.lower()
    if any(marker_text in lower for marker_text in _UPSTREAM_UNAVAILABLE_MARKERS):
        return True
    return any(
        re.search(pattern, text, flags=re.IGNORECASE) for pattern in _HTTP_429_PATTERNS
    )


def _request_count(log_delta: str) -> int:
    access_log_count = log_delta.count("POST /v1/messages")
    service_log_count = log_delta.count("API_REQUEST:")
    structured_log_count = log_delta.count(
        '"event": "free_claude_code.api.request.received"'
    )
    return max(access_log_count, service_log_count, structured_log_count)


def _git_sha() -> str:
    """Return the source checkout SHA for a smoke report, when available."""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            check=False,
            text=True,
            timeout=1.0,
        )
    except OSError, subprocess.TimeoutExpired:
        return "unknown"
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else "unknown"


def _marker(scope: str, prefix: str) -> str:
    return f"FCC_{scope}_{prefix}_{uuid.uuid4().hex[:8].upper()}"


def _excerpt(value: str | None, *, max_chars: int = 2400) -> str:
    if value is None:
        value = ""
    if len(value) <= max_chars:
        return redacted(value)
    return redacted(value[-max_chars:])


def _coerce_timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
