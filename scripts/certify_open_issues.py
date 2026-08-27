#!/usr/bin/env python3
"""Run shared deterministic/live certification steps for remaining issues."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from smoke.lib.open_issue_certification import (
    CERTIFICATION_STEPS,
    CertificationStep,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the existing shared smoke/contract machinery for remaining "
            "Harness certification issues. Live steps are opt-in."
        )
    )
    parser.add_argument(
        "--issue",
        type=int,
        action="append",
        help="limit to one or more GitHub issue numbers",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="include live/provider/device steps in addition to deterministic steps",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print selected steps without executing them",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path(".smoke-results/open-issue-certification.json"),
        help="metadata-only execution receipt path",
    )
    return parser


def _selected_steps(issues: set[int] | None, *, include_live: bool) -> list[CertificationStep]:
    return [
        step
        for step in CERTIFICATION_STEPS
        if (issues is None or issues.intersection(step.issues))
        and (include_live or step.evidence == "deterministic")
    ]


def _resolved_argv(step: CertificationStep) -> list[str]:
    argv = list(step.argv)
    if argv and argv[0] == "python":
        argv[0] = sys.executable
    return argv


def _plan(step: CertificationStep) -> dict[str, object]:
    return {
        "step_id": step.step_id,
        "issues": list(step.issues),
        "evidence": step.evidence,
        "argv": _resolved_argv(step),
        "environment": dict(step.environment),
        "required_environment": list(step.required_environment),
        "description": step.description,
    }


def _run_step(step: CertificationStep, *, root: Path) -> dict[str, object]:
    missing = [key for key in step.required_environment if not os.environ.get(key)]
    if missing:
        return {
            **_plan(step),
            "status": "unverified",
            "reason": "missing_environment",
            "missing_environment": missing,
            "returncode": None,
            "duration_s": 0.0,
        }

    environment = os.environ.copy()
    environment.update(dict(step.environment))
    started = time.monotonic()
    result = subprocess.run(
        _resolved_argv(step),
        cwd=root,
        env=environment,
        check=False,
    )
    return {
        **_plan(step),
        "status": "passed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "duration_s": round(max(0.0, time.monotonic() - started), 3),
    }


def main() -> int:
    args = _parser().parse_args()
    selected = _selected_steps(
        set(args.issue) if args.issue else None,
        include_live=args.live,
    )
    if not selected:
        raise SystemExit("no certification steps matched the requested issue selection")

    if args.list:
        print(json.dumps([_plan(step) for step in selected], indent=2, sort_keys=True))
        return 0

    root = Path(__file__).resolve().parents[1]
    results = [_run_step(step, root=root) for step in selected]
    receipt = {
        "schema": "fcc.open-issue-certification.v1",
        "live_included": bool(args.live),
        "requested_issues": sorted(set(args.issue)) if args.issue else [],
        "steps": results,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    failed = any(result["status"] == "failed" for result in results)
    unverified = any(result["status"] == "unverified" for result in results)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    if failed:
        return 1
    if unverified:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
