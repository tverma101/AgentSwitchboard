"""Regression tests for model-picker identity readability."""

from free_claude_code.cli.model_picker_readable_tui import (
    _compact_exact_ref,
    _readable_inspector_title,
    _readable_row_label,
)
from free_claude_code.cli.model_picker_tui import ModelListButton


def test_row_keeps_exact_identity_when_friendly_names_collapse() -> None:
    refs = (
        "open_router/openai/gpt-model",
        "opencode/openai/gpt-model",
        "opencode_go/openai/gpt-model",
    )
    labels = []
    for ref in refs:
        row = ModelListButton(
            ref,
            "GPT Model",
            price="PRICE?",
            is_default=False,
            enabled=True,
            selected=False,
        )
        labels.append(_readable_row_label(row))

    assert len(set(labels)) == len(refs)
    for ref, label in zip(refs, labels, strict=True):
        assert "GPT Model" in label
        assert ref in label


def test_compact_identity_preserves_variant_bearing_tail() -> None:
    ref = (
        "very_long_gateway_provider/openai/"
        "gpt-5.6-codex-ultra-long-distinct-variant-name"
    )
    compact = _compact_exact_ref(ref, limit=44)

    assert len(compact) <= 44
    assert compact.startswith("very_long_gate")
    assert compact.endswith("distinct-variant-name")


def test_inspector_puts_exact_model_ref_on_its_own_line() -> None:
    ref = "open_router/openai/gpt-5.6-codex"
    title = _readable_inspector_title("GPT Model", ref)

    assert title.splitlines() == ["GPT Model", ref]
