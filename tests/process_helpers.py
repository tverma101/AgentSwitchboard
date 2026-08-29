import contextlib
import os
import signal
import subprocess
from collections.abc import Mapping, Sequence


def terminate_process_tree(pid: int) -> None:
    """Stop a timed-out test process and its descendants."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
        return

    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        pass

    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)


def run_bounded(
    args: Sequence[str],
    *,
    env: Mapping[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    """Run a non-interactive test command with group-wide timeout cleanup."""
    if os.name == "nt":
        process: subprocess.Popen[str] = subprocess.Popen(
            list(args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=dict(env),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        process = subprocess.Popen(
            list(args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=dict(env),
            start_new_session=True,
        )

    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        terminate_process_tree(process.pid)
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            error.cmd,
            error.timeout,
            output=stdout or "",
            stderr=stderr or "",
        ) from error

    return subprocess.CompletedProcess(
        list(args),
        process.returncode,
        stdout or "",
        stderr or "",
    )
