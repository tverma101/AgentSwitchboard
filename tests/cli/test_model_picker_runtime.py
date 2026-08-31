from unittest.mock import patch

import pytest

from free_claude_code.cli.model_picker_runtime import ReliableModelControlCenterApp
from free_claude_code.config.model_catalog import ModelCatalogMode
from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings

MODEL = "openai/gpt-5.6-sol"


def _settings(*, model: str = MODEL) -> Settings:
    return Settings.model_construct(
        host="0.0.0.0",
        port=8082,
        anthropic_auth_token="freecc",
        model=model,
        reasoning_policy=ReasoningPreference.CLIENT,
        model_catalog_mode=ModelCatalogMode.CURATED,
        model_catalog_allowlist=model,
    )


@pytest.mark.asyncio
async def test_picker_rechecks_server_snapshot_after_short_ui_cache() -> None:
    now = [10.0]
    catalog = {"models": [MODEL], "catalog_models": [MODEL]}
    app = ReliableModelControlCenterApp(_settings(), supervisor=None)

    with (
        patch(
            "free_claude_code.cli.control_tui.get_models",
            return_value=catalog,
        ) as get_models,
        patch(
            "free_claude_code.cli.model_picker_runtime.time.monotonic",
            side_effect=lambda: now[0],
        ),
    ):
        await app._load_model_catalog()
        now[0] += 0.5
        await app._load_model_catalog()
        assert get_models.call_count == 1

        now[0] += 0.6
        await app._load_model_catalog()
        assert get_models.call_count == 2


def test_settings_reload_invalidates_picker_snapshot() -> None:
    app = ReliableModelControlCenterApp(_settings(), supervisor=None)
    app._model_catalog_result = {"models": [MODEL]}
    app._model_picker_snapshot_at = 42.0
    latest = _settings(model="openai/gpt-5.6-luna")

    with patch("free_claude_code.cli.control_tui.get_settings", return_value=latest):
        app._refresh_settings_snapshot()

    assert app.settings is latest
    assert app._model_catalog_result is None
    assert app._model_picker_snapshot_at == 0.0
