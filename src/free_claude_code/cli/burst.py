"""Run Harness CI on an ephemeral GitHub Codespaces runner."""

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass

_CODESPACE_REPOSITORY = "tverma101/Rumple"
_HARNESS_REPOSITORY = "tverma101/Harness"
_CODESPACE_BRANCH = "main"
_DISPLAY_NAME = "Rumple Harness Burst"
_RUNNER_LABEL = "harness-burst"
_DEFAULT_MACHINE = "basicLinux32gb"
_DEFAULT_IDLE_TIMEOUT = "10m"
_DEFAULT_TIMEOUT_SECONDS = 900
_DEFAULT_POLL_SECONDS = 5.0


class BurstError(RuntimeError):
    """A recoverable failure while provisioning or using the burst runner."""


@dataclass(frozen=True)
class Codespace:
    name: str
    state: str
    display_name: str


def _run(command: Sequence[str], *, capture: bool = True) -> str:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=capture,
            text=True,
        )
    except OSError as exc:
        raise BurstError(f"could not run {command[0]}: {exc}") from exc

    if completed.returncode != 0:
        detail = completed.stderr if isinstance(completed.stderr, str) else ""
        detail = detail.strip() or f"exit status {completed.returncode}"
        raise BurstError(f"{' '.join(command)} failed: {detail}")
    return completed.stdout.strip() if isinstance(completed.stdout, str) else ""


def _json(command: Sequence[str]) -> object:
    try:
        return json.loads(_run(command))
    except json.JSONDecodeError as exc:
        raise BurstError(f"{command[0]} returned invalid JSON") from exc


def _codespaces() -> list[Codespace]:
    payload = _json(
        [
            "gh",
            "codespace",
            "list",
            "--repo",
            _CODESPACE_REPOSITORY,
            "--limit",
            "100",
            "--json",
            "name,state,displayName",
        ]
    )
    if not isinstance(payload, list):
        raise BurstError("GitHub returned an unexpected Codespaces list")

    codespaces: list[Codespace] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        state = item.get("state")
        display_name = item.get("displayName")
        if isinstance(name, str) and isinstance(state, str):
            codespaces.append(
                Codespace(
                    name=name,
                    state=state,
                    display_name=display_name if isinstance(display_name, str) else "",
                )
            )
    return codespaces


def _select_codespace(codespaces: list[Codespace]) -> Codespace | None:
    named = [item for item in codespaces if item.display_name == _DISPLAY_NAME]
    if len(named) == 1:
        return named[0]
    if len(named) > 1:
        names = ", ".join(item.name for item in named)
        raise BurstError(f"multiple Rumple burst Codespaces found: {names}")
    if len(codespaces) == 1:
        return codespaces[0]
    if codespaces:
        names = ", ".join(item.name for item in codespaces)
        raise BurstError(
            "multiple Rumple Codespaces found; set the burst display name "
            f"to '{_DISPLAY_NAME}' or remove the ambiguity: {names}"
        )
    return None


def _wait_for_codespace(
    *, known_names: set[str], timeout: float, poll_seconds: float
) -> Codespace:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates = [
            item
            for item in _codespaces()
            if item.name not in known_names and item.display_name == _DISPLAY_NAME
        ]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            names = ", ".join(item.name for item in candidates)
            raise BurstError(f"multiple new Rumple Codespaces found: {names}")
        time.sleep(poll_seconds)
    raise BurstError("timed out waiting for the Rumple Codespace to appear")


def _wait_for_available(name: str, *, timeout: float, poll_seconds: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = next((item for item in _codespaces() if item.name == name), None)
        if current is not None and current.state.casefold() == "available":
            return
        time.sleep(poll_seconds)
    raise BurstError(f"timed out waiting for Codespace {name} to become available")


def _start_codespace(codespace: Codespace) -> None:
    state = codespace.state.casefold()
    if state in {"available", "running", "starting", "creating"}:
        return
    _run(["gh", "api", "--method", "POST", f"user/codespaces/{codespace.name}/start"])


def _create_codespace(
    *, machine: str, idle_timeout: str, timeout: float, poll_seconds: float
) -> Codespace:
    existing_names = {item.name for item in _codespaces()}
    _run(
        [
            "gh",
            "codespace",
            "create",
            "--repo",
            _CODESPACE_REPOSITORY,
            "--branch",
            _CODESPACE_BRANCH,
            "--devcontainer-path",
            ".devcontainer/devcontainer.json",
            "--machine",
            machine,
            "--idle-timeout",
            idle_timeout,
            "--display-name",
            _DISPLAY_NAME,
        ]
    )
    return _wait_for_codespace(
        known_names=existing_names,
        timeout=timeout,
        poll_seconds=poll_seconds,
    )


def _wait_for_runner(*, timeout: float, poll_seconds: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = _json(["gh", "api", f"repos/{_HARNESS_REPOSITORY}/actions/runners"])
        runners = payload.get("runners", []) if isinstance(payload, dict) else []
        if isinstance(runners, list):
            for runner in runners:
                if not isinstance(runner, dict) or runner.get("status") != "online":
                    continue
                labels = runner.get("labels", [])
                label_names: set[str] = set()
                if isinstance(labels, list):
                    for label in labels:
                        if not isinstance(label, dict):
                            continue
                        label_name = label.get("name")
                        if isinstance(label_name, str):
                            label_names.add(label_name)
                if _RUNNER_LABEL in label_names and not runner.get("busy", False):
                    return
        time.sleep(poll_seconds)
    raise BurstError(f"timed out waiting for the {_RUNNER_LABEL} runner")


def _run_ids(ref: str) -> set[int]:
    payload = _json(
        [
            "gh",
            "run",
            "list",
            "--repo",
            _HARNESS_REPOSITORY,
            "--workflow",
            "tests.yml",
            "--branch",
            ref,
            "--event",
            "workflow_dispatch",
            "--limit",
            "50",
            "--json",
            "databaseId",
        ]
    )
    if not isinstance(payload, list):
        return set()
    run_ids: set[int] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        run_id = item.get("databaseId")
        if isinstance(run_id, int):
            run_ids.add(run_id)
    return run_ids


def _wait_for_run(
    ref: str, *, old_ids: set[int], timeout: float, poll_seconds: float
) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = _json(
            [
                "gh",
                "run",
                "list",
                "--repo",
                _HARNESS_REPOSITORY,
                "--workflow",
                "tests.yml",
                "--branch",
                ref,
                "--event",
                "workflow_dispatch",
                "--limit",
                "20",
                "--json",
                "databaseId",
            ]
        )
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                run_id = item.get("databaseId")
                if isinstance(run_id, int) and run_id not in old_ids:
                    return run_id
        time.sleep(poll_seconds)
    raise BurstError("timed out waiting for the dispatched Harness CI run")


def _stop_codespace(name: str) -> None:
    _run(["gh", "codespace", "stop", "--codespace", name])


def _current_ref() -> str:
    try:
        ref = _run(["git", "branch", "--show-current"])
    except BurstError:
        return "main"
    return ref or "main"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fcc burst",
        description="Run Harness CI on the Rumple Codespaces burst runner.",
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=("run", "stop"),
        default="run",
        help="run CI (default) or stop the selected Rumple Codespace.",
    )
    parser.add_argument(
        "--ref",
        default=None,
        help="Harness branch to test (defaults to the current local branch).",
    )
    parser.add_argument(
        "--machine",
        default=_DEFAULT_MACHINE,
        help="Codespaces machine name (default: basicLinux32gb, 2 cores).",
    )
    parser.add_argument("--idle-timeout", default=_DEFAULT_IDLE_TIMEOUT)
    parser.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--poll-seconds", type=float, default=_DEFAULT_POLL_SECONDS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Provision Rumple, dispatch Harness CI, and always stop Rumple."""
    args = _parser().parse_args(argv)
    if args.timeout <= 0 or args.poll_seconds <= 0:
        raise BurstError("--timeout and --poll-seconds must be positive")

    if args.action == "stop":
        codespace = _select_codespace(_codespaces())
        if codespace is None:
            print("No Rumple Codespace exists.")
        elif codespace.state.casefold() in {"shutdown", "stopped"}:
            print(f"Rumple Codespace {codespace.name} is already stopped.")
        else:
            _stop_codespace(codespace.name)
            print(f"Stopped Rumple Codespace {codespace.name}.")
        return 0

    ref = args.ref or _current_ref()
    codespace: Codespace | None = None
    failure: Exception | None = None
    try:
        codespace = _select_codespace(_codespaces())
        if codespace is None:
            codespace = _create_codespace(
                machine=args.machine,
                idle_timeout=args.idle_timeout,
                timeout=args.timeout,
                poll_seconds=args.poll_seconds,
            )
        _start_codespace(codespace)
        _wait_for_available(
            codespace.name,
            timeout=args.timeout,
            poll_seconds=args.poll_seconds,
        )
        _wait_for_runner(timeout=args.timeout, poll_seconds=args.poll_seconds)
        old_ids = _run_ids(ref)
        _run(
            [
                "gh",
                "workflow",
                "run",
                "tests.yml",
                "--repo",
                _HARNESS_REPOSITORY,
                "--ref",
                ref,
                "--field",
                f"runner_label={_RUNNER_LABEL}",
            ]
        )
        run_id = _wait_for_run(
            ref,
            old_ids=old_ids,
            timeout=args.timeout,
            poll_seconds=args.poll_seconds,
        )
        _run(
            [
                "gh",
                "run",
                "watch",
                str(run_id),
                "--repo",
                _HARNESS_REPOSITORY,
                "--compact",
                "--exit-status",
            ],
            capture=False,
        )
    except Exception as exc:
        failure = exc
    finally:
        if codespace is not None:
            try:
                _stop_codespace(codespace.name)
            except BurstError as exc:
                if failure is None:
                    failure = exc
                else:
                    print(f"warning: failed to stop Codespace: {exc}", file=sys.stderr)

    if failure is not None:
        raise failure
    return 0
