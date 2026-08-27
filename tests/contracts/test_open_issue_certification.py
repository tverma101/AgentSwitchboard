"""Contracts for the consolidated remaining-issue certification plan."""

from smoke.lib.open_issue_certification import (
    CERTIFICATION_STEPS,
    steps_for_issue,
    uncovered_issues,
)


def test_all_current_engineering_issues_have_a_shared_evidence_path() -> None:
    current_open = {
        11,
        15,
        16,
        17,
        18,
        19,
        21,
        23,
        31,
        41,
        55,
        59,
        60,
        61,
        63,
        66,
        98,
        102,
        122,
    }

    # #66 is the tracker board and #122 is the later learning feature; every
    # other current issue is now a certification/evidence lane with a shared step.
    assert uncovered_issues(current_open) == (66, 122)


def test_live_steps_are_not_returned_by_default() -> None:
    assert steps_for_issue(21) == ()
    assert [step.step_id for step in steps_for_issue(21, include_live=True)] == [
        "codex-browser-device"
    ]


def test_deterministic_issue_plan_stays_stable_and_reuses_existing_machinery() -> None:
    issue_15 = steps_for_issue(15)

    assert [step.step_id for step in issue_15] == [
        "responses-torture-and-attribution",
        "transport-synthetic-responses",
    ]
    assert all(step.evidence == "deterministic" for step in issue_15)
    assert all(step.argv[0] == "python" for step in CERTIFICATION_STEPS)


def test_live_steps_are_explicitly_labeled() -> None:
    live = [step for step in CERTIFICATION_STEPS if step.evidence == "live"]

    assert {step.step_id for step in live} == {
        "literal-claude-cli",
        "provider-live-matrix",
        "codex-browser-device",
    }
    assert any(step.environment for step in live)
