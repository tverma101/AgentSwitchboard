"""Behavior tests for the tuiui-inspired model settings desktop."""

from types import MappingProxyType
from typing import Any
from unittest.mock import patch

import pytest
from textual.containers import Horizontal
from textual.widgets import Button, Static

from free_claude_code.cli.model_picker_tui import (
    ModelListButton,
    TuiuiControlCenterApp,
)
from free_claude_code.config.model_catalog import ModelCatalogMode
from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings

MODEL_A = "open_router/provider/alpha"
MODEL_B = "open_router/provider/beta"
CLICK_ROW = (2, 0)
CLICK_BUTTON = (2, 1)
TEST_TERMINAL_SIZE = (120, 40)


def _settings(*, beta_enabled: bool = False) -> Settings:
    allowlist = f"{MODEL_A}, {MODEL_B}" if beta_enabled else MODEL_A
    return Settings.model_construct(
        host="0.0.0.0",
        port=8082,
        anthropic_auth_token="freecc",
        model=MODEL_A,
        reasoning_policy=ReasoningPreference.CLIENT,
        model_catalog_mode=ModelCatalogMode.CURATED,
        model_catalog_allowlist=allowlist,
    )


def _catalog() -> dict[str, object]:
    return {
        "models": [MODEL_A],
        "catalog_models": [MODEL_A, MODEL_B],
        "model_labels": {MODEL_A: "Alpha", MODEL_B: "Beta"},
        "catalog_model_labels": {MODEL_A: "Alpha", MODEL_B: "Beta"},
        "model_evidence": {},
        "catalog_model_evidence": {},
    }


def _row(app: TuiuiControlCenterApp, model: str) -> ModelListButton:
    return next(row for row in app.query(ModelListButton) if row.model_ref == model)


async def _inspect_model(app: TuiuiControlCenterApp, pilot: Any, model: str) -> None:
    row = _row(app, model)
    row.focus()
    await pilot.pause()
    assert await pilot.click(row, offset=CLICK_ROW)
    await pilot.pause()
    assert app._model_inspector_ref == model


@pytest.mark.asyncio
async def test_model_picker_uses_compact_browser_and_inspector() -> None:
    app = TuiuiControlCenterApp(_settings(), supervisor=None)
    with patch(
        "free_claude_code.cli.control_tui.get_models",
        return_value=_catalog(),
    ):
        async with app.run_test(size=TEST_TERMINAL_SIZE) as pilot:
            await app._show_page("models")
            await pilot.pause()

            assert app.query_one("#model-workspace", Horizontal).display
            assert len(app.query(ModelListButton)) == 2
            assert _row(app, MODEL_A).has_class("model-row-default")
            assert _row(app, MODEL_A).has_class("model-row-enabled")
            assert not _row(app, MODEL_B).has_class("model-row-enabled")
            assert not app.query_one("#model-toggle-access", Button).disabled
            assert app.query_one("#model-set-default", Button).disabled
            assert "Alpha" in str(
                app.query_one("#model-inspector-title", Static).content
            )


@pytest.mark.asyncio
async def test_default_model_can_be_disabled_with_automatic_handoff() -> None:
    app = TuiuiControlCenterApp(_settings(), supervisor=None)
    with patch(
        "free_claude_code.cli.control_tui.get_models",
        return_value=_catalog(),
    ):
        async with app.run_test(size=TEST_TERMINAL_SIZE) as pilot:
            await app._show_page("models")
            await pilot.pause()

            access = app.query_one("#model-toggle-access", Button)
            access.focus()
            await pilot.pause()
            assert await pilot.click(access, offset=CLICK_BUTTON)
            await pilot.pause()

            assert MODEL_A not in app._model_pending_enabled
            assert MODEL_B in app._model_pending_enabled
            assert app._model_pending_default == MODEL_B
            assert not _row(app, MODEL_A).has_class("model-row-enabled")
            assert _row(app, MODEL_B).has_class("model-row-default")
            assert not app.query_one("#models-save", Button).disabled


@pytest.mark.asyncio
async def test_nondefault_model_enable_is_direct_and_mouse_clickable() -> None:
    app = TuiuiControlCenterApp(_settings(), supervisor=None)
    with patch(
        "free_claude_code.cli.control_tui.get_models",
        return_value=_catalog(),
    ):
        async with app.run_test(size=TEST_TERMINAL_SIZE) as pilot:
            await app._show_page("models")
            await pilot.pause()
            await _inspect_model(app, pilot, MODEL_B)

            access = app.query_one("#model-toggle-access", Button)
            assert str(access.label) == "Enable model"
            access.focus()
            await pilot.pause()
            assert await pilot.click(access, offset=CLICK_BUTTON)
            await pilot.pause()

            assert MODEL_B in app._model_pending_enabled
            assert _row(app, MODEL_B).has_class("model-row-enabled")
            assert str(access.label) == "Disable model"


@pytest.mark.asyncio
async def test_model_rows_support_enter_and_space_keyboard_selection() -> None:
    app = TuiuiControlCenterApp(_settings(), supervisor=None)
    with patch(
        "free_claude_code.cli.control_tui.get_models",
        return_value=_catalog(),
    ):
        async with app.run_test(size=TEST_TERMINAL_SIZE) as pilot:
            await app._show_page("models")
            await pilot.pause()

            beta = _row(app, MODEL_B)
            beta.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert app._model_inspector_ref == MODEL_B

            alpha = _row(app, MODEL_A)
            alpha.focus()
            await pilot.press("space")
            await pilot.pause()
            assert app._model_inspector_ref == MODEL_A
            assert app._model_pending_enabled == {MODEL_A}


@pytest.mark.asyncio
async def test_nondefault_model_disable_is_direct_and_mouse_clickable() -> None:
    app = TuiuiControlCenterApp(_settings(beta_enabled=True), supervisor=None)
    with patch(
        "free_claude_code.cli.control_tui.get_models",
        return_value=_catalog(),
    ):
        async with app.run_test(size=TEST_TERMINAL_SIZE) as pilot:
            await app._show_page("models")
            await pilot.pause()
            await _inspect_model(app, pilot, MODEL_B)

            access = app.query_one("#model-toggle-access", Button)
            assert str(access.label) == "Disable model"
            access.focus()
            await pilot.pause()
            assert await pilot.click(access, offset=CLICK_BUTTON)
            await pilot.pause()

            assert MODEL_B not in app._model_pending_enabled
            assert not _row(app, MODEL_B).has_class("model-row-enabled")
            assert str(access.label) == "Enable model"


@pytest.mark.asyncio
async def test_model_picker_batches_default_and_visibility_into_one_save() -> None:
    app = TuiuiControlCenterApp(_settings(), supervisor=None)
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
        async with app.run_test(size=TEST_TERMINAL_SIZE) as pilot:
            await app._show_page("models")
            await pilot.pause()
            await _inspect_model(app, pilot, MODEL_B)

            make_default = app.query_one("#model-set-default", Button)
            make_default.focus()
            await pilot.pause()
            assert await pilot.click(make_default, offset=CLICK_BUTTON)
            await pilot.pause()
            assert app._model_pending_default == MODEL_B

            app._model_inspector_ref = MODEL_A
            app._refresh_model_editor_widgets()
            access = app.query_one("#model-toggle-access", Button)
            access.focus()
            await pilot.pause()
            assert await pilot.click(access, offset=CLICK_BUTTON)
            await pilot.pause()

            save = app.query_one("#models-save", Button)
            save.focus()
            await pilot.pause()
            assert await pilot.click(save, offset=CLICK_BUTTON)
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
    app = TuiuiControlCenterApp(_settings(), supervisor=None)
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
        async with app.run_test(size=TEST_TERMINAL_SIZE) as pilot:
            await app._show_page("models")
            await pilot.pause()

            app._model_inspector_ref = MODEL_B
            app.make_inspected_model_default()
            assert not app.query_one("#models-discard", Button).disabled

            discard = app.query_one("#models-discard", Button)
            discard.focus()
            await pilot.pause()
            assert await pilot.click(discard, offset=CLICK_BUTTON)
            await pilot.pause()

            assert app._model_pending_default == MODEL_A
            assert app._model_pending_enabled == {MODEL_A}
            assert _row(app, MODEL_A).has_class("model-row-default")
            assert app.query_one("#models-save", Button).disabled

    apply.assert_not_called()


@pytest.mark.asyncio
async def test_model_picker_preserves_pending_edits_across_catalog_refresh() -> None:
    app = TuiuiControlCenterApp(_settings(), supervisor=None)
    with patch("free_claude_code.cli.control_tui.get_models", return_value=_catalog()):
        async with app.run_test(size=TEST_TERMINAL_SIZE) as pilot:
            await app._show_page("models")
            await pilot.pause()

            app._model_inspector_ref = MODEL_B
            app.make_inspected_model_default()
            assert app._model_pending_default == MODEL_B

            await app._show_page("models", force=True, refresh_models=True)
            await pilot.pause()

            assert app._model_pending_default == MODEL_B
            assert not app.query_one("#models-save", Button).disabled


@pytest.mark.asyncio
async def test_model_picker_reconciles_external_default_when_no_edit_is_pending() -> (
    None
):
    app = TuiuiControlCenterApp(_settings(), supervisor=None)
    with patch("free_claude_code.cli.control_tui.get_models", return_value=_catalog()):
        async with app.run_test(size=TEST_TERMINAL_SIZE) as pilot:
            await app._show_page("models")
            await pilot.pause()
            app.settings.model = MODEL_B

            await app._show_page("models", force=True)
            await pilot.pause()

            assert app._model_initial_default == MODEL_B
            assert app._model_pending_default == MODEL_B
            assert app.query_one("#models-save", Button).disabled


@pytest.mark.asyncio
async def test_model_picker_preserves_unavailable_configured_default() -> None:
    settings = _settings()
    settings.model = "gateway/missing"
    app = TuiuiControlCenterApp(settings, supervisor=None)
    with patch("free_claude_code.cli.control_tui.get_models", return_value=_catalog()):
        async with app.run_test(size=TEST_TERMINAL_SIZE) as pilot:
            await app._show_page("models")
            await pilot.pause()

            assert app._model_pending_default == "gateway/missing"
            assert app.query_one("#models-save", Button).disabled
            assert app._model_inspector_ref == MODEL_A
            assert app.query_one("#model-inspector-title", Static).content == "Alpha"


@pytest.mark.asyncio
async def test_model_picker_handles_mapping_and_malformed_catalog_shapes() -> None:
    app = TuiuiControlCenterApp(_settings(), supervisor=None)
    result = MappingProxyType(
        {
            "models": "not-a-sequence",
            "catalog_models": (MODEL_A, None, ""),
            "model_labels": None,
            "catalog_model_labels": None,
            "model_evidence": None,
            "catalog_model_evidence": None,
        }
    )
    with patch("free_claude_code.cli.control_tui.get_models", return_value=result):
        async with app.run_test(size=TEST_TERMINAL_SIZE) as pilot:
            await app._show_page("models")
            await pilot.pause()

            assert len(app.query(ModelListButton)) == 1
            assert app._model_visible_refs == (MODEL_A,)


@pytest.mark.asyncio
async def test_model_picker_malformed_save_response_stays_open() -> None:
    app = TuiuiControlCenterApp(_settings(), supervisor=None)
    with (
        patch("free_claude_code.cli.control_tui.get_models", return_value=_catalog()),
        patch(
            "free_claude_code.cli.model_picker_tui.apply_admin_values",
            return_value=[],
        ) as apply,
    ):
        async with app.run_test(size=TEST_TERMINAL_SIZE) as pilot:
            await app._show_page("models")
            await pilot.pause()
            app._model_inspector_ref = MODEL_B
            app.make_inspected_model_default()
            await app.save_model_changes()
            await pilot.pause()

            assert app.page == "models"
            assert app._model_pending_default == MODEL_B

    apply.assert_called_once()


@pytest.mark.asyncio
async def test_model_catalog_is_requested_once_per_picker_render() -> None:
    app = TuiuiControlCenterApp(_settings(), supervisor=None)
    with patch(
        "free_claude_code.cli.control_tui.get_models", return_value=_catalog()
    ) as get_models:
        async with app.run_test(size=TEST_TERMINAL_SIZE) as pilot:
            await app._show_page("models")
            await pilot.pause()

    assert get_models.call_count == 1
