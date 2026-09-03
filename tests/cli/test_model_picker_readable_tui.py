"""Regression tests for model-picker identity readability."""

from unittest.mock import patch

import pytest
from textual.widgets import Footer, Header, Static

from free_claude_code.cli.model_picker_readable_tui import (
    ReadableModelControlCenterApp,
    _compact_exact_ref,
    _readable_inspector_title,
    _readable_row_label,
)
from free_claude_code.cli.model_picker_tui import ModelListButton
from free_claude_code.config.model_catalog import ModelCatalogMode
from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings

MODEL_REF = "open_router/openai/gpt-5.6-codex"


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
    title = _readable_inspector_title("GPT Model", MODEL_REF)

    assert title.splitlines() == ["GPT Model", MODEL_REF]


@pytest.mark.asyncio
async def test_models_page_keeps_navigation_chrome_and_exact_identity_visible() -> None:
    settings = Settings.model_construct(
        host="0.0.0.0",
        port=8082,
        anthropic_auth_token="freecc",
        model=MODEL_REF,
        reasoning_policy=ReasoningPreference.CLIENT,
        model_catalog_mode=ModelCatalogMode.CURATED,
        model_catalog_allowlist=MODEL_REF,
    )
    catalog = {
        "models": [MODEL_REF],
        "catalog_models": [MODEL_REF],
        "model_labels": {MODEL_REF: "GPT Model"},
        "catalog_model_labels": {MODEL_REF: "GPT Model"},
        "model_evidence": {},
        "catalog_model_evidence": {},
    }
    app = ReadableModelControlCenterApp(settings, supervisor=None)

    with patch(
        "free_claude_code.cli.control_tui.get_models",
        return_value=catalog,
    ):
        async with app.run_test(size=(120, 40)) as pilot:
            await app._show_page("models")
            await pilot.pause()

            row = next(iter(app.query(ModelListButton)))
            inspector = app.query_one("#model-inspector-title", Static)

            assert MODEL_REF in str(row.label)
            assert MODEL_REF in str(inspector.content)
            assert app.query_one("#sidebar").display
            assert app.query_one("#summary").display
            assert app.query_one("#window-titlebar").display
            assert not app.query("#window-controls")
            assert app.query_one(Header).display
            assert app.query_one(Footer).display
            assert app.query_one("#actions").display
