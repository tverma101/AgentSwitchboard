"""Shared certification plan for the remaining Harness integration issues.

The registry deliberately points at existing contract/smoke/benchmark machinery.
It prevents every issue from growing its own runner and keeps live/provider/device
claims explicitly separate from deterministic evidence.
"""

from dataclasses import dataclass
from typing import Literal

EvidenceKind = Literal["deterministic", "live"]


@dataclass(frozen=True, slots=True)
class CertificationStep:
    step_id: str
    issues: tuple[int, ...]
    evidence: EvidenceKind
    argv: tuple[str, ...]
    environment: tuple[tuple[str, str], ...] = ()
    required_environment: tuple[str, ...] = ()
    description: str = ""
    timeout_seconds: float = 300.0


CERTIFICATION_STEPS: tuple[CertificationStep, ...] = (
    CertificationStep(
        step_id="responses-torture-and-attribution",
        issues=(15, 16, 18),
        evidence="deterministic",
        argv=(
            "python",
            "-m",
            "pytest",
            "-n",
            "0",
            "tests/core/openai_responses/test_provider_stream.py",
            "tests/core/test_fault_attribution.py",
            "tests/contracts/test_native_harness_comparator.py",
            "-q",
        ),
        description=(
            "Exercise Responses stream/tool/reasoning failure semantics plus the "
            "shared native-vs-Harness attribution comparator."
        ),
    ),
    CertificationStep(
        step_id="media-conformance",
        issues=(19, 23, 41),
        evidence="deterministic",
        argv=(
            "python",
            "-m",
            "pytest",
            "-n",
            "0",
            "tests/contracts/test_media_conformance.py",
            "tests/contracts/test_codex_browser_device.py",
            "-q",
        ),
        description=(
            "Pin image/tool-result protocol behavior and the payload-free browser "
            "device-canary wrapper before any live visual run."
        ),
    ),
    CertificationStep(
        step_id="compaction-contracts",
        issues=(59, 60, 61, 63),
        evidence="deterministic",
        argv=(
            "python",
            "-m",
            "pytest",
            "-n",
            "0",
            "tests/contracts/test_auto_compact_receipt.py",
            "tests/contracts/test_claude_compaction_inheritance.py",
            "tests/contracts/test_compaction_continuity.py",
            "-q",
        ),
        description=(
            "Validate the already-landed compact/continuity/inheritance receipt "
            "contracts without pretending they are live Claude evidence."
        ),
    ),
    CertificationStep(
        step_id="terminal-provider-policy-contracts",
        issues=(102,),
        evidence="deterministic",
        argv=(
            "python",
            "-m",
            "pytest",
            "-n",
            "0",
            "tests/cli/test_terminal_control_center.py",
            "tests/cli/test_codex_connect.py",
            "tests/runtime/test_session_policy_wiring.py",
            "-q",
        ),
        description=(
            "Recheck the terminal/Codex connected-account boundary and session-wide "
            "helper/provider isolation used by the native-tool path."
        ),
    ),
    CertificationStep(
        step_id="reviewer-scar-core",
        issues=(122,),
        evidence="deterministic",
        argv=(
            "python",
            "-m",
            "pytest",
            "-n",
            "0",
            "tests/learning/test_reviewer_scars.py",
            "-q",
        ),
        description=(
            "Validate reviewer-pack selection, DROP-by-default scar promotion, profile "
            "isolation, bounded context slices, dedupe/state history, and X1 tickets."
        ),
    ),
    CertificationStep(
        step_id="transport-synthetic-responses",
        issues=(11, 15, 16, 17),
        evidence="deterministic",
        argv=(
            "python",
            "scripts/benchmark_opencode_go_transport.py",
            "--mode",
            "synthetic",
            "--model",
            "muse-spark-1.2-contributor",
            "--samples",
            "1,10,100",
            "--max-tokens",
            "4096",
        ),
        description="Measure the Responses transport path without provider spend.",
    ),
    CertificationStep(
        step_id="transport-synthetic-messages",
        issues=(11, 16),
        evidence="deterministic",
        argv=(
            "python",
            "scripts/benchmark_opencode_go_transport.py",
            "--mode",
            "synthetic",
            "--model",
            "qwen3.7-plus",
            "--samples",
            "1,10,100",
        ),
        description="Measure the native Messages transport path without provider spend.",
    ),
    CertificationStep(
        step_id="literal-claude-cli",
        issues=(31, 55, 59, 61, 63, 102),
        evidence="live",
        argv=(
            "python",
            "-m",
            "pytest",
            "smoke/product",
            "-n",
            "0",
            "-s",
            "--tb=short",
        ),
        environment=(("FCC_LIVE_SMOKE", "1"), ("FCC_SMOKE_TARGETS", "cli")),
        description=(
            "Run the existing literal-Claude product matrix through FCC. Individual "
            "opt-in subagent/compaction cases remain controlled by their documented "
            "FCC_SMOKE_* flags."
        ),
    ),
    CertificationStep(
        step_id="provider-live-matrix",
        issues=(11, 15, 16, 17, 18, 19, 41, 60, 102),
        evidence="live",
        argv=(
            "python",
            "-m",
            "pytest",
            "smoke/product",
            "-n",
            "0",
            "-s",
            "--tb=short",
        ),
        environment=(("FCC_LIVE_SMOKE", "1"), ("FCC_SMOKE_TARGETS", "providers")),
        description=(
            "Run existing provider product scenarios. Provider credentials/models "
            "remain explicit environment-owned inputs."
        ),
    ),
    CertificationStep(
        step_id="codex-browser-device",
        issues=(21, 102),
        evidence="live",
        argv=("python", "scripts/smoke_codex_browser.py"),
        description=(
            "Exercise the installed Codex browser plugin with a disposable local tab; "
            "no model/provider generation is involved."
        ),
    ),
)


def steps_for_issue(
    issue: int,
    *,
    include_live: bool = False,
) -> tuple[CertificationStep, ...]:
    """Return all applicable certification steps in stable registry order."""

    return tuple(
        step
        for step in CERTIFICATION_STEPS
        if issue in step.issues and (include_live or step.evidence == "deterministic")
    )


def uncovered_issues(issues: set[int]) -> tuple[int, ...]:
    """Return issue IDs with no registered deterministic or live evidence step."""

    covered = {issue for step in CERTIFICATION_STEPS for issue in step.issues}
    return tuple(sorted(issues - covered))
