"""Run the deterministic FCC Learning lifecycle benchmark."""

import argparse
import difflib
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from free_claude_code.learning.engine import apply_learning_result
from free_claude_code.learning.stop_hook import enqueue_stop
from free_claude_code.learning.store import LearningStore

_FIXTURE_PATH = Path(__file__).with_name("fixtures") / "learning_skill_corpus.json"


def _load_fixture() -> dict[str, Any]:
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("learning fixture must contain an object and cases")
    return payload


def _case(case_id: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    for case in cases:
        if case.get("id") == case_id:
            return case
    raise KeyError(case_id)


def _check(case_id: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"id": case_id, "passed": bool(passed), "detail": detail}


def run(*, commit_sha: str | None = None) -> dict[str, Any]:
    started_ns = time.perf_counter_ns()
    fixture = _load_fixture()
    cases = [case for case in fixture["cases"] if isinstance(case, dict)]
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="fcc-learning-benchmark-") as root:
        root_path = Path(root)
        project = root_path / "project"
        (project / ".git").mkdir(parents=True)
        claude = root_path / "claude"
        os.environ["CLAUDE_CONFIG_DIR"] = str(claude)
        database_path = root_path / "learning.db"
        store = LearningStore(database_path)
        sqlite_bytes_before = database_path.stat().st_size

        memory_id, inserted = store.add_memory(
            scope="global",
            project_key=str(project),
            text="Prefer concise release notes.",
            confidence=0.96,
            source="user_explicit",
        )
        replaced = store.replace_memory(
            memory_id=memory_id,
            project_key=str(project),
            scope="global",
            text="Prefer concise release notes with test evidence.",
            confidence=0.98,
            source="user_explicit",
            reason="user correction",
            evidence="user_explicit",
        )
        checks.append(
            _check(
                _case("memory-preference-replacement", cases)["id"],
                inserted
                and replaced
                and store.get_memory(memory_id, project_key=str(project))["text"]
                == "Prefer concise release notes with test evidence.",
                "replacement is visible under the original memory id",
            )
        )

        blocked = apply_learning_result(
            result={
                "memory_actions": [
                    {
                        "action": "add",
                        "scope": "global",
                        "text": "Never use the provider after one timeout.",
                        "confidence": 0.99,
                        "evidence_kind": "successful_workflow",
                    }
                ],
                "skill": None,
            },
            cwd=str(project),
            store=store,
            attribution={"fault_domain": "opencode_gateway", "success": False},
        )
        checks.append(
            _check(
                _case("memory-contradiction-rejection", cases)["id"],
                blocked == {"memories": 0, "skills": 0},
                "infrastructure-attributed failure produced no durable learning",
            )
        )

        removed = store.remove_memory(
            memory_id,
            project_key=str(project),
            reason="explicit forget",
            evidence="user_explicit",
        )
        history = store.memory_history(memory_id, project_key=str(project))
        checks.append(
            _check(
                _case("memory-explicit-forget", cases)["id"],
                removed
                and store.get_memory(memory_id, project_key=str(project)) is None
                and [row["action"] for row in history] == ["add", "replace", "remove"],
                "forget removes injection source and preserves audit history",
            )
        )

        skill_receipts: list[dict[str, Any]] = []
        first_skill = {
            "memory_actions": [],
            "skill": {
                "action": "create",
                "name": "safe-release",
                "description": "Release only after validation.",
                "instructions": (
                    "Run the focused tests, verify the diff, and check the final "
                    "status before handoff."
                ),
                "scope": "global",
                "confidence": 0.98,
                "evidence_kind": "successful_workflow",
            },
        }
        created = apply_learning_result(
            result=first_skill, cwd=str(project), store=store
        )
        skill_path = claude / "skills" / "fcc-auto-safe-release" / "SKILL.md"
        created_text = (
            skill_path.read_text(encoding="utf-8") if created["skills"] else ""
        )
        updated = apply_learning_result(
            result={
                "memory_actions": [],
                "skill": {
                    **first_skill["skill"],
                    "action": "update",
                    "instructions": (
                        "Run focused tests, verify the diff, and check the final "
                        "status, then record the receipt before handoff."
                    ),
                },
            },
            cwd=str(project),
            store=store,
        )
        previous = skill_path.read_text(encoding="utf-8")
        update_diff = list(
            difflib.unified_diff(
                created_text.splitlines(),
                previous.splitlines(),
                fromfile="revision-1/SKILL.md",
                tofile="revision-2/SKILL.md",
            )
        )
        skill_receipts.append(
            {
                "case_id": _case("skill-create-update", cases)["id"],
                "decision": "accepted",
                "checks": ["frontmatter", "validation_contract", "revision_saved"],
                "skill_diff": {
                    "added_lines": sum(line.startswith("+") for line in update_diff)
                    - 1,
                    "removed_lines": sum(line.startswith("-") for line in update_diff)
                    - 1,
                },
            }
        )
        checks.append(
            _check(
                _case("skill-create-update", cases)["id"],
                created == {"memories": 0, "skills": 1}
                and updated == {"memories": 0, "skills": 1}
                and len(store.skill_revisions("fcc-auto-safe-release")) == 2,
                "accepted skill revisions retain the prior version",
            )
        )
        rejected = apply_learning_result(
            result={
                "memory_actions": [],
                "skill": {
                    **first_skill["skill"],
                    "action": "update",
                    "instructions": "Run focused tests and verify the diff before handoff.",
                },
            },
            cwd=str(project),
            store=store,
        )
        rejected_text = skill_path.read_text(encoding="utf-8")
        skill_receipts.append(
            {
                "case_id": _case("skill-poisoned-update", cases)["id"],
                "decision": "rejected",
                "checks": ["validation_contract"],
                "skill_diff": {
                    "added_lines": 0,
                    "removed_lines": 0,
                    "unchanged_sha256": hashlib.sha256(
                        rejected_text.encode()
                    ).hexdigest(),
                },
            }
        )
        checks.append(
            _check(
                _case("skill-poisoned-update", cases)["id"],
                rejected == {"memories": 0, "skills": 0}
                and skill_path.read_text(encoding="utf-8") == previous,
                "dropped validation step is rejected without changing the file",
            )
        )
        rolled_back = store.rollback_skill("fcc-auto-safe-release", 1)
        checks.append(
            _check(
                _case("skill-rollback", cases)["id"],
                rolled_back == skill_path
                and hashlib.sha256(skill_path.read_bytes()).hexdigest()
                == store.skill_revisions("fcc-auto-safe-release")[-1]["digest"],
                "rollback restores revision bytes and digest metadata",
            )
        )

        store.record_prompt(
            session_id="benchmark-session", cwd=str(project), prompt="Run tests"
        )
        enqueue_started = time.perf_counter_ns()
        first_queue_id = enqueue_stop(
            {
                "session_id": "benchmark-session",
                "cwd": str(project),
                "last_assistant_message": "Tests passed.",
            },
            store,
        )
        second_queue_id = enqueue_stop(
            {
                "session_id": "benchmark-session",
                "cwd": str(project),
                "last_assistant_message": "Tests passed.",
            },
            store,
        )
        enqueue_ms = (time.perf_counter_ns() - enqueue_started) / 1_000_000
        claimed = store.claim_learning(lease_seconds=0.01)
        if claimed is not None:
            time.sleep(1.02)
        recovered = store.claim_learning(lease_seconds=0.01)
        checks.append(
            _check(
                _case("queue-recovery", cases)["id"],
                first_queue_id == second_queue_id
                and recovered is not None
                and store.queue_counts().get("processing") == 1,
                "duplicate enqueue is idempotent and stale processing is reclaimable",
            )
        )

        passed = sum(1 for check in checks if check["passed"])
        runtime_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        return {
            "schema": "fcc.learning.benchmark.v1",
            "fixture_version": fixture.get("fixture_version"),
            "commit_sha": commit_sha or "working-tree",
            "model_route": "deterministic_local",
            "model_id": None,
            "token_usage": None,
            "skill_receipts": skill_receipts,
            "checks": checks,
            "summary": {
                "passed": passed,
                "failed": len(checks) - passed,
                "runtime_ms": round(runtime_ms, 6),
                "enqueue_ms": round(enqueue_ms, 6),
                "sqlite_bytes_before": sqlite_bytes_before,
                "sqlite_bytes_after": database_path.stat().st_size,
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--commit-sha")
    args = parser.parse_args()
    receipt = run(commit_sha=args.commit_sha)
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if receipt["summary"]["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
