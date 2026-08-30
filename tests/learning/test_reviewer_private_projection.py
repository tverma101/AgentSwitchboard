from free_claude_code.learning.reviewer_flow import parse_exit_ticket
from free_claude_code.learning.reviewer_scars import (
    ExitStatus,
    SubagentExitTicket,
    VerificationLevel,
)


def test_parent_projection_keeps_actionable_result_but_hides_private_receipt_fields() -> None:
    canary = "PRIVATE_RECEIPT_CANARY_7F91"
    ticket = SubagentExitTicket(
        status=ExitStatus.DONE,
        implemented=True,
        verification=VerificationLevel.TESTS,
        blocker="-",
        cave="backend_absent",
        learn_candidate=True,
        evidence=("pr:148", canary),
        next_action="check_registration_first",
    )

    parsed = parse_exit_ticket(ticket.compact())
    context = parsed.parent_context()

    assert "status=DONE" in context
    assert "implemented=1" in context
    assert "verification=tests" in context
    assert "cave=backend_absent" in context
    assert "next=check_registration_first" in context
    assert canary not in context
    assert "pr:148" not in context
    assert "X1|" not in context
    assert "ev=" not in context
    assert "learn=" not in context


def test_invalid_exit_projection_does_not_expose_internal_parser_reason() -> None:
    parsed = parse_exit_ticket("not an exit ticket")

    context = parsed.parent_context()

    assert "status=UNVERIFIED" in context
    assert parsed.reason == "missing_x1"
    assert "missing_x1" not in context
    assert "X1" not in context
