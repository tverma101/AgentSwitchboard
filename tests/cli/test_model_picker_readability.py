from unittest.mock import patch

import pytest
from textual.widgets import Static

from free_claude_code.cli.model_picker_readable_tui import (
    ReadableModelControlCenterApp,
)
from free_claude_code.cli.model_picker_tui import ModelListButton
from free_claude_code.config.model_catalog import ModelCatalogMode
from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings

MODEL_A = "open_router/openai/gpt-model"
MODEL_B = "open_router/azure/gpt-model"


def _settings() -> Settings:
    return Settings.model_construct(
        host="0.0.0.0",
        port=8082,
        anthropic_auth_token="freecc",
        model=MODEL_A,
        reasoning_policy=ReasoningPreference.CLIENT,
        model_catalog_mode=ModelCatalogMode.CURATED,
        model_catalog_allowlist=MODEL_A,
    )


def _catalog() -> dict[str, object]:
    return {
        "models": [MODEL_A],
        "catalog_models": [MODEL_A, MODEL_B],
        # Reproduce the broken upstream/server label shape directly: the UI
        # still must not hide which route the human is selecting.
        "model_labels": {MODEL_A: "GPT Model", MODEL_B: "GPT Model"},
        "catalog_model_labels": {MODEL_A: "GPT Model", MODEL_B: "GPT Model"},
        "model_evidence": {},
        "catalog_model_evidence": {},
    }


@pytest.mark.asyncio
async def test_models_page_zooms_workspace_and_never_hides_exact_model_identity() -> None:
    app = ReadableModelControlCenterApp(_settings(), supervisor=None)
    with patch("free_claude_code.cli.control_tui.get_models", return_value=_catalog()):
        async with app.run_test(size=(120, 40)) as pilot:
            await app._show_page("models")
            await pilot.pause()

            assert not app.query_one("#sidebar").display
            assert not app.query_one("#summary").display

            rows = list(app.query(ModelListButton))
            assert len(rows) == 2
            for row in rows:
                assert row.model_ref in str(row.label)
            assert str(rows[0].label) != str(rows[1].label)

            app._model_inspector_ref = MODEL_B
            app._refresh_model_editor_widgets()
            title = str(app.query_one("#model-inspector-title", Static).content)
            assert "GPT Model" in title
            assert MODEL_B in title
