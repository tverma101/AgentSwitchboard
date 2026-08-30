"""Behavior tests for the GUI-like model settings editor."""

from unittest.mock import patch

import pytest
from textual.widgets import Button, Static

from free_claude_code.cli.model_picker_tui import (
    GuiModelControlCenterApp,
    ModelAccessButton,
    ModelDefaultButton,
)
from free_claude_code.config.model_catalog import ModelCatalogMode
from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings

MODEL_A = "open_router/provider/alpha"
MODEL_B = "open_router/provider/beta"
CLICK_INSIDE = (2, 1)


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
        "model_labels": {
            MODEL_A: "Alpha",
            MODEL_B: "Beta",
        },
        "catalog_model_labels": {
            MODEL_A: "Alpha",
            MODEL_B: "Beta",
        },
        "model_evidence": {},
        "catalog_model_evidence": {},
    }


def _default_button(
    app: GuiModelControlCenterApp,
    model: str,
) -> ModelDefaultButton:
    return next(
        button for button in app.query(ModelDefaultButton) if button.model_ref == model
    )


def _access_button(
    app: GuiModelControlCenterApp,
    model: str,
) -> ModelAccessButton:
    return next(
        button for button in app.query(ModelAccessButton) if button.model_ref == model
    )


@pytest.mark.asyncio
async def test_model_picker_exposes_direct_default_access_and_save_controls() -> None:
    app = GuiModelControlCenterApp(_settings(), supervisor=None)
    with patch(
        "free_claude_code.cli.control_tui.get_models",
        return_value=_catalog(),
    ):
        async with app.run_test() as pilot:
            await app._show_page("models")
            await pilot.pause()

            assert len(app.query(ModelDefaultButton)) == 2
            assert len(app.query(ModelAccessButton)) == 2
            assert _default_button(app, MODEL_A).has_class("model-default-pending")
            assert _access_button(app, MODEL_A).disabled
            assert not _access_button(app, MODEL_B).disabled
            assert app.query_one("#models-save", Button).disabled
            assert app.query_one("#models-discard", Button).disabled

            summary = str(app.query_one("#summary", Static).content)
            assert "Click a model name to make it the default" in summary
            assert "Press Save changes once when done" in summary


@pytest.mark.asyncio
async def test_model_picker_batches_default_and_visibility_into_one_save() -> None:
    app = GuiModelControlCenterApp(_settings(), supervisor=None)
    with (
        patch(
            "free_claude_code.cli.control_tui.get_models",
            return_value=_catalog(),
        ),
        patch(
            "free_claude_code.cli.model_picker_tui.apply_admin_values",
            return_value={"applied": True},
        ) as apply,
    ):
        async with app.run_test() as pilot:
            await app._show_page("models")
            await pilot.pause()

            assert await pilot.click(
                _default_button(app, MODEL_B), offset=CLICK_INSIDE
            )
            await pilot.pause()
            assert _default_button(app, MODEL_B).has_class("model-default-pending")
            assert _access_button(app, MODEL_B).disabled
            assert not _access_button(app, MODEL_A).disabled

            assert await pilot.click(
                _access_button(app, MODEL_A), offset=CLICK_INSIDE
            )
            await pilot.pause()
            assert not app.query_one("#models-save", Button).disabled

            assert await pilot.click(
                app.query_one("#models-save", Button), offset=CLICK_INSIDE
            )
            await pilot.pause()

    apply.assert_called_once()
    assert apply.call_args.args[1] == {
        "MODEL": MODEL_B,
        "MODEL_CATALOG_MODE": "curated",
        "MODEL_CATALOG_ALLOWLIST": MODEL_B,
    }
    assert app.settings.model == MODEL_B
    assert app.settings.model_catalog_mode is ModelCatalogMode.CURATED
    assert app.settings.model_catalog_allowlist == MODEL_B


@pytest.mark.asyncio
async def test_model_picker_discard_restores_saved_state_without_writing() -> None:
    app = GuiModelControlCenterApp(_settings(), supervisor=None)
    with (
        patch(
            "free_claude_code.cli.control_tui.get_models",
            return_value=_catalog(),
        ),
        patch(
            "free_claude_code.cli.model_picker_tui.apply_admin_values",
            return_value={"applied": True},
        ) as apply,
    ):
        async with app.run_test() as pilot:
            await app._show_page("models")
            await pilot.pause()

            assert await pilot.click(
                _default_button(app, MODEL_B), offset=CLICK_INSIDE
            )
            await pilot.pause()
            assert not app.query_one("#models-discard", Button).disabled

            assert await pilot.click(
                app.query_one("#models-discard", Button), offset=CLICK_INSIDE
            )
            await pilot.pause()

            assert _default_button(app, MODEL_A).has_class("model-default-pending")
            assert _access_button(app, MODEL_A).disabled
            assert app.query_one("#models-save", Button).disabled

    apply.assert_not_called()


@pytest.mark.asyncio
async def test_model_picker_keeps_default_enabled_when_user_switches_models() -> None:
    app = GuiModelControlCenterApp(_settings(), supervisor=None)
    with patch(
        "free_claude_code.cli.control_tui.get_models",
        return_value=_catalog(),
    ):
        async with app.run_test() as pilot:
            await app._show_page("models")
            await pilot.pause()

            assert await pilot.click(
                _default_button(app, MODEL_B), offset=CLICK_INSIDE
            )
            await pilot.pause()

            assert MODEL_B in app._model_pending_enabled
            assert _access_button(app, MODEL_B).disabled
            assert _access_button(app, MODEL_B).has_class("model-access-enabled")
