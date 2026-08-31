"""Behavior tests for the Harlequin-derived AgentSwitchboard control center.

The ``App.run_test()`` / Pilot pattern is adapted from Harlequin's functional
TUI tests at commit fcfaa6c524a6cd47e17701d931eac0243c8c85b6.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Button, DataTable, Input, OptionList, Select, Static

from free_claude_code.application.connected_accounts import ConnectedAccountLoginMode
from free_claude_code.cli.control_tui import ControlCenterApp, ModelToggleButton
from free_claude_code.cli.repo_picker import RepoEntry
from free_claude_code.config.model_catalog import ModelCatalogMode
from free_claude_code.config.reasoning import ReasoningPreference
from free_claude_code.config.settings import Settings
from free_claude_code.core.branding import PRODUCT_NAME


def _settings() -> Settings:
    return Settings.model_construct(
        host="0.0.0.0",
        port=8082,
        anthropic_auth_token="freecc",
        model="opencode_go/muse-spark-1.2-contributor",
        reasoning_policy=ReasoningPreference.CLIENT,
    )


@pytest.mark.asyncio
async def test_control_tui_mounts_persistent_navigation_shell() -> None:
    with (
        patch(
            "free_claude_code.cli.control_tui.fcc_provider_account_summary",
            return_value="fcc@example.com",
        ),
        patch(
            "free_claude_code.cli.control_tui.codex_accounts.active_account_summary",
            return_value="codex@example.com (profile personal)",
        ),
        patch(
            "free_claude_code.cli.harlequin_app_base.load_theme",
            return_value="harlequin",
        ),
        patch(
            "free_claude_code.cli.control_tui.repository_from_path",
            return_value=RepoEntry(
                "checkout",
                "/workspace/checkout",
                "main",
                "acme/service",
            ),
        ),
    ):
        app = ControlCenterApp(_settings(), supervisor=None)
        async with app.run_test() as pilot:
            await pilot.pause()
            nav = app.query_one("#nav", OptionList)
            assert nav.option_count >= 10
            assert app.TITLE == PRODUCT_NAME
            assert str(app.query_one("#sidebar-title", Static).content) == PRODUCT_NAME
            assert app.query_one("#main-panel")
            assert app.query_one("#actions")
            assert app.query_one("#launch-claude")
            assert app.query_one("#launch-danger")
            assert app.theme == "harlequin"
            dashboard = str(app.query_one(".dashboard-card", Static).content)
            assert "OpenAI / ChatGPT  fcc@example.com" in dashboard
            assert "FCC Account" not in dashboard
            assert "Repository   acme/service · /workspace/checkout" in dashboard


@pytest.mark.asyncio
async def test_provider_table_overlays_live_connected_account_state() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    config = {
        "provider_status": [
            {
                "provider_id": "openai",
                "display_name": "OpenAI / ChatGPT",
                "kind": "connected_account",
                "status": "disconnected",
                "label": "Not connected",
            }
        ],
        "fields": [],
    }
    with (
        patch(
            "free_claude_code.cli.control_tui.fcc_provider_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.codex_accounts.active_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.get_admin_config",
            return_value=config,
        ),
        patch(
            "free_claude_code.cli.control_tui.connected_account_status",
            return_value={
                "state": "connected",
                "connected": True,
                "email": "fcc@example.com",
                "model_count": 6,
            },
        ),
    ):
        async with app.run_test() as pilot:
            await app._show_page("providers")
            await pilot.pause()
            table = app.query_one("#table", DataTable)
            row = table.get_row("openai")
            assert row[0] == "OpenAI / ChatGPT"
            assert "Connected" in str(row[1])
            assert "fcc@example.com" in str(row[1])


@pytest.mark.asyncio
async def test_browser_login_waits_for_real_connected_state() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    config = {
        "provider_status": [
            {
                "provider_id": "openai",
                "display_name": "OpenAI / ChatGPT",
                "kind": "connected_account",
                "status": "disconnected",
                "label": "Not connected",
            }
        ],
        "fields": [],
    }
    statuses: list[dict[str, object]] = [
        {
            "state": "connecting",
            "connected": False,
            "model_count": 0,
        },
        {
            "state": "connected",
            "connected": True,
            "email": "fcc@example.com",
            "model_count": 6,
        },
    ]

    def status(*_args: object, **_kwargs: object) -> dict[str, object]:
        try:
            return statuses.pop(0)
        except StopIteration:
            return {
                "state": "connected",
                "connected": True,
                "email": "fcc@example.com",
                "model_count": 6,
            }

    with (
        patch(
            "free_claude_code.cli.control_tui.fcc_provider_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.codex_accounts.active_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.get_admin_config",
            return_value=config,
        ),
        patch(
            "free_claude_code.cli.control_tui.start_connected_account_login",
            return_value={
                "state": "connecting",
                "authorization_url": "https://example.test/login",
            },
        ),
        patch(
            "free_claude_code.cli.control_tui.connected_account_status",
            side_effect=status,
        ),
        patch("free_claude_code.cli.control_tui.webbrowser.open") as browser_open,
    ):
        async with app.run_test() as pilot:
            app.selected_provider = "openai"
            await app._start_fcc_login(ConnectedAccountLoginMode.BROWSER)
            await pilot.pause()
            browser_open.assert_called_once_with("https://example.test/login")
            assert app._oauth_provider == "openai"
            await app._poll_live_state()
            await pilot.pause()
            assert app._oauth_provider is None


@pytest.mark.asyncio
async def test_repo_navigation_never_uses_nested_input_prompts() -> None:
    with (
        patch(
            "free_claude_code.cli.control_tui.fcc_provider_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.codex_accounts.active_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.repository_from_path",
            return_value=None,
        ),
        patch("free_claude_code.cli.control_tui.default_roots", return_value=()),
        patch(
            "free_claude_code.cli.control_tui.github_authenticated_user",
            return_value=None,
        ),
        patch("free_claude_code.cli.control_tui.cache_is_fresh", return_value=False),
        patch("free_claude_code.cli.control_tui.discover_repos", return_value=[]),
        patch("free_claude_code.cli.control_tui.save_cached_repos"),
        patch(
            "builtins.input", side_effect=AssertionError("TUI must not call input()")
        ),
    ):
        app = ControlCenterApp(_settings(), supervisor=None)
        async with app.run_test() as pilot:
            await app._show_page("repos")
            await pilot.pause()
            table = app.query_one("#table", DataTable)
            assert table.row_count == 0
            assert app.query_one("#repo-open")
            assert app.query_one("#repo-refresh")


@pytest.mark.asyncio
async def test_repo_refresh_replaces_actions_without_duplicate_widget_ids() -> None:
    with (
        patch(
            "free_claude_code.cli.control_tui.fcc_provider_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.codex_accounts.active_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.repository_from_path",
            return_value=None,
        ),
        patch("free_claude_code.cli.control_tui.default_roots", return_value=()),
        patch(
            "free_claude_code.cli.control_tui.github_authenticated_user",
            return_value=None,
        ),
        patch("free_claude_code.cli.control_tui.cache_is_fresh", return_value=False),
        patch(
            "free_claude_code.cli.control_tui.discover_repos", return_value=[]
        ) as discover,
        patch("free_claude_code.cli.control_tui.save_cached_repos"),
        patch(
            "free_claude_code.cli.control_tui.get_models",
            return_value={"models": []},
        ),
    ):
        app = ControlCenterApp(_settings(), supervisor=None)
        async with app.run_test() as pilot:
            await app._show_page("repos")
            await app._show_page("models")
            await app._show_page("repos", force=True)
            await pilot.pause()
            assert discover.call_count == 1

            await app.repo_refresh()
            await pilot.pause()
            assert discover.call_count == 2

            assert len(app.query("#repo-select")) == 1
            assert len(app.query("#repo-open")) == 1
            assert len(app.query("#repo-refresh")) == 1


@pytest.mark.asyncio
async def test_repositories_page_uses_live_local_inventory() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    repo = RepoEntry(
        PRODUCT_NAME,
        str(Path(__file__).resolve().parents[2]),
        "main",
        "tverma101/AgentSwitchboard",
    )
    with (
        patch(
            "free_claude_code.cli.control_tui.fcc_provider_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.codex_accounts.active_account_summary",
            return_value="not connected",
        ),
        patch("free_claude_code.cli.control_tui.default_roots", return_value=()),
        patch(
            "free_claude_code.cli.control_tui.github_authenticated_user",
            return_value=None,
        ),
        patch("free_claude_code.cli.control_tui.cache_is_fresh", return_value=False),
        patch(
            "free_claude_code.cli.control_tui.discover_repos",
            return_value=[repo],
        ) as discover,
        patch("free_claude_code.cli.control_tui.save_cached_repos"),
    ):
        async with app.run_test() as pilot:
            await app._show_page("repos")
            await pilot.pause()

            table = app.query_one("#table", DataTable)
            assert table.row_count == 1
            assert table.get_row(repo.path) == [
                "tverma101/AgentSwitchboard",
                f"● {PRODUCT_NAME}",
                "main",
                repo.display_path,
            ]
            assert "Local Git repositories (1 found)" in str(
                app.query_one("#summary", Static).content
            )
            discover.assert_called_once_with(())


@pytest.mark.asyncio
async def test_repositories_page_uses_fresh_cache_without_scanning() -> None:
    repo = RepoEntry(
        PRODUCT_NAME,
        str(Path(__file__).resolve().parents[2]),
        "main",
        "tverma101/AgentSwitchboard",
    )
    app = ControlCenterApp(_settings(), supervisor=None)
    with (
        patch("free_claude_code.cli.control_tui.cache_is_fresh", return_value=True),
        patch(
            "free_claude_code.cli.control_tui.load_cached_repos",
            return_value=[repo],
        ) as load,
        patch("free_claude_code.cli.control_tui.discover_repos") as discover,
        patch("free_claude_code.cli.control_tui.save_cached_repos") as save,
    ):
        async with app.run_test() as pilot:
            await app._show_page("repos")
            await pilot.pause()
            await app._show_page("repos", force=True)
            await pilot.pause()

    load.assert_called_once()
    discover.assert_not_called()
    save.assert_not_called()


@pytest.mark.asyncio
async def test_repositories_page_accepts_local_checkout_without_github_authentication() -> (
    None
):
    repo = RepoEntry("local-checkout", "/tmp/local-checkout", "main", "")
    app = ControlCenterApp(_settings(), supervisor=None, selected_repo=repo)
    with (
        patch(
            "free_claude_code.cli.control_tui.fcc_provider_account_summary",
            return_value="not connected",
        ),
        patch(
            "free_claude_code.cli.control_tui.codex_accounts.active_account_summary",
            return_value="not connected",
        ),
        patch("free_claude_code.cli.control_tui.default_roots", return_value=()),
        patch(
            "free_claude_code.cli.control_tui.github_authenticated_user",
            return_value=None,
        ),
        patch("free_claude_code.cli.control_tui.cache_is_fresh", return_value=False),
        patch(
            "free_claude_code.cli.control_tui.discover_repos",
            return_value=[repo],
        ) as discover,
        patch("free_claude_code.cli.control_tui.save_cached_repos") as save,
    ):
        async with app.run_test() as pilot:
            await app._show_page("repos")
            await pilot.pause()

            table = app.query_one("#table", DataTable)
            canonical_path = str(Path(repo.path).resolve())
            assert table.get_row(canonical_path) == [
                "local-checkout",
                "● local-checkout",
                "main",
                canonical_path,
            ]
            assert app.selected_repo is not None
            assert app.selected_repo.path == canonical_path

    discover.assert_called_once_with(())
    save.assert_called_once()


@pytest.mark.asyncio
async def test_repository_page_deduplicates_rows_and_restores_default_cursor() -> None:
    first = RepoEntry("first", "/tmp/first", "main", "acme/service")
    selected = RepoEntry("second", "/tmp/second", "feature/ui", "acme/service")
    app = ControlCenterApp(_settings(), supervisor=None, selected_repo=selected)
    with (
        patch("free_claude_code.cli.control_tui.default_roots", return_value=()),
        patch("free_claude_code.cli.control_tui.cache_is_fresh", return_value=False),
        patch(
            "free_claude_code.cli.control_tui.discover_repos",
            return_value=[selected, first, selected],
        ),
        patch("free_claude_code.cli.control_tui.save_cached_repos"),
    ):
        async with app.run_test() as pilot:
            await app._show_page("repos")
            await pilot.pause()

            table = app.query_one("#table", DataTable)
            assert table.row_count == 2
            assert table.cursor_row == 1
            assert table.get_row(str(Path(selected.path).resolve()))[1] == "● second"


@pytest.mark.asyncio
async def test_repository_page_refreshes_selected_metadata_for_same_checkout() -> None:
    stale = RepoEntry("checkout", "/tmp/checkout", "old", "acme/old")
    fresh = RepoEntry("checkout", "/tmp/checkout", "feature/ui", "acme/service")
    app = ControlCenterApp(_settings(), supervisor=None, selected_repo=stale)
    with (
        patch("free_claude_code.cli.control_tui.default_roots", return_value=()),
        patch("free_claude_code.cli.control_tui.cache_is_fresh", return_value=False),
        patch(
            "free_claude_code.cli.control_tui.discover_repos",
            return_value=[fresh],
        ),
        patch("free_claude_code.cli.control_tui.save_cached_repos"),
    ):
        async with app.run_test() as pilot:
            await app._show_page("repos")
            await pilot.pause()

            assert app.selected_repo is not None
            assert app.selected_repo.path == str(Path(fresh.path).resolve())
            assert app.selected_repo.branch == "feature/ui"
            assert (
                app.query_one("#table", DataTable).get_row(
                    str(Path(fresh.path).resolve())
                )[0]
                == "acme/service"
            )


@pytest.mark.asyncio
async def test_open_repo_path_selects_a_local_checkout() -> None:
    repo = RepoEntry("external", "/tmp/external", "main", "gitlab.com/acme/external")
    app = ControlCenterApp(_settings(), supervisor=None, selected_repo=repo)
    with (
        patch(
            "free_claude_code.cli.control_tui.repository_from_path",
            return_value=repo,
        ) as from_path,
        patch("free_claude_code.cli.control_tui.default_roots", return_value=()),
        patch("free_claude_code.cli.control_tui.cache_is_fresh", return_value=False),
        patch(
            "free_claude_code.cli.control_tui.discover_repos",
            return_value=[repo],
        ),
        patch("free_claude_code.cli.control_tui.save_cached_repos"),
    ):
        async with app.run_test() as pilot:
            await app._open_repo_path("~/external")
            await pilot.pause()

            assert app.selected_repo is not None
            assert app.selected_repo.identity == repo.identity
            assert (
                app.query_one("#table", DataTable).get_row(
                    str(Path(repo.path).resolve())
                )[1]
                == "● external"
            )

    from_path.assert_called_once()


@pytest.mark.asyncio
async def test_open_repo_path_keeps_invalid_path_unselected() -> None:
    with patch(
        "free_claude_code.cli.control_tui.repository_from_path",
        return_value=None,
    ) as from_path:
        app = ControlCenterApp(_settings(), supervisor=None, selected_repo=None)
        async with app.run_test() as pilot:
            await app._open_repo_path("~/not-a-repository")
            await pilot.pause()

    from_path.assert_called()
    assert app.selected_repo is None


@pytest.mark.asyncio
async def test_models_page_filters_and_manages_explicit_catalog() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    with (
        patch(
            "free_claude_code.cli.control_tui.get_models",
            return_value={
                "models": ["opencode_zen/hidden", app.settings.model],
                "catalog_models": ["opencode_zen/hidden", app.settings.model],
                "model_labels": {},
                "catalog_model_labels": {},
                "model_evidence": {},
                "catalog_model_evidence": {},
            },
        ),
        patch(
            "free_claude_code.cli.control_tui.apply_admin_values",
            return_value={"applied": True},
        ) as apply,
        patch(
            "free_claude_code.cli.control_tui.get_settings",
            return_value=app.settings,
        ),
    ):
        async with app.run_test() as pilot:
            await app._show_page("models")
            await pilot.pause()

            assert app.query_one("#model-provider", Select)
            assert app.query_one("#model-price", Select)
            assert app.query_one("#model-search", Input)
            assert app.query_one("#models-enable")
            assert app.query_one("#models-disable")
            assert app.query_one("#models-disable-all")
            model_list = app.query_one("#model-list", VerticalScroll)
            rows = list(model_list.query(ModelToggleButton))
            assert len(rows) == 2
            assert isinstance(app.focused, ModelToggleButton)
            assert app.focused.model_ref == app.settings.model

            await pilot.press("space")
            await pilot.pause()
            assert app.selected_models == {app.settings.model}

            app.model_search = "hidden"
            await app._show_page("models", force=True)
            await pilot.pause()
            assert (
                len(
                    app.query_one("#model-list", VerticalScroll).query(
                        ModelToggleButton
                    )
                )
                == 1
            )
            assert app.selected_models == {app.settings.model}

            app.model_search = ""
            app.selected_models.add("opencode_zen/hidden")
            await app.enable_selected_models()
            await pilot.pause()
            values = apply.call_args.args[1]
            assert values["MODEL_CATALOG_MODE"] == "curated"
            assert set(values["MODEL_CATALOG_ALLOWLIST"].split(", ")) == {
                app.settings.model,
                "opencode_zen/hidden",
            }
            assert app.settings.model_catalog_mode is ModelCatalogMode.CURATED

            app.selected_models.add("opencode_zen/hidden")
            await app.disable_selected_models()
            await pilot.pause()
            assert apply.call_args.args[1] == {
                "MODEL_CATALOG_MODE": "curated",
                "MODEL_CATALOG_ALLOWLIST": app.settings.model,
            }


@pytest.mark.asyncio
async def test_models_page_keeps_disabled_discoveries_selectable_and_never_auto_selects() -> (
    None
):
    app = ControlCenterApp(_settings(), supervisor=None)
    catalog = {
        "models": [app.settings.model],
        "catalog_models": [app.settings.model, "open_router/free-model"],
        "model_labels": {},
        "catalog_model_labels": {},
        "model_evidence": {},
        "catalog_model_evidence": {},
    }
    with (
        patch(
            "free_claude_code.cli.control_tui.get_models",
            return_value=catalog,
        ),
        patch(
            "free_claude_code.cli.control_tui.apply_admin_values",
            return_value={"applied": True},
        ) as apply,
    ):
        async with app.run_test() as pilot:
            await app._show_page("models")
            await pilot.pause()
            model_list = app.query_one("#model-list", VerticalScroll)
            rows = list(model_list.query(ModelToggleButton))
            assert len(rows) == 2
            assert not any(row.has_class("model-row-pending") for row in rows)

            await app.disable_all_models()
            await pilot.pause()
            assert (
                len(
                    app.query_one("#model-list", VerticalScroll).query(
                        ModelToggleButton
                    )
                )
                == 2
            )
            assert app.selected_models == set()

            model_list = app.query_one("#model-list", VerticalScroll)
            rows = list(model_list.query(ModelToggleButton))
            rows[app._model_list_index(model_list, "open_router/free-model")].focus()
            await pilot.press("space")
            await pilot.pause()
            assert app.selected_models == {"open_router/free-model"}
            selected_row = rows[
                app._model_list_index(model_list, "open_router/free-model")
            ]
            assert selected_row.has_class("model-row-pending")
            await app.enable_selected_models()
            await pilot.pause()

    assert apply.call_args.args[1] == {
        "MODEL_CATALOG_MODE": "curated",
        "MODEL_CATALOG_ALLOWLIST": "open_router/free-model",
    }


@pytest.mark.asyncio
async def test_models_page_sorts_free_first_and_filters_only_explicitly() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    free_model = "open_router/provider/free-model"
    unknown_model = "open_router/provider/unknown-model"
    paid_model = "open_router/provider/paid-model"
    catalog = {
        "models": [free_model, unknown_model, paid_model],
        "catalog_models": [paid_model, unknown_model, free_model],
        "model_labels": {},
        "catalog_model_labels": {},
        "model_evidence": {},
        "catalog_model_evidence": {
            free_model: {"is_free": True, "pricing": {}},
            unknown_model: {"is_free": None, "pricing": {}},
            paid_model: {
                "is_free": False,
                "pricing": {"prompt": 0.000001, "completion": 0.000002},
            },
        },
    }
    with patch("free_claude_code.cli.control_tui.get_models", return_value=catalog):
        async with app.run_test() as pilot:
            await app._show_page("models")
            await pilot.pause()
            rows = list(
                app.query_one("#model-list", VerticalScroll).query(ModelToggleButton)
            )
            assert [row.model_ref for row in rows] == [
                free_model,
                unknown_model,
                paid_model,
            ]
            assert "Price: free first" in app._model_summary_text
            assert "Free: 1" in app._model_summary_text

            app.selected_models.add(paid_model)
            app.model_price_filter = "free-only"
            await app._show_page("models", force=True)
            await pilot.pause()

            rows = list(
                app.query_one("#model-list", VerticalScroll).query(ModelToggleButton)
            )
            assert [row.model_ref for row in rows] == [free_model]
            assert app.selected_models == {paid_model}
            assert "Price: free only" in app._model_summary_text


@pytest.mark.asyncio
async def test_models_page_caches_discovery_until_explicit_refresh() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    model = "open_router/provider/visible-model"
    catalog = {
        "models": [model],
        "catalog_models": [model],
        "model_labels": {},
        "catalog_model_labels": {},
        "model_evidence": {},
        "catalog_model_evidence": {},
    }
    with patch(
        "free_claude_code.cli.control_tui.get_models", return_value=catalog
    ) as get_models:
        async with app.run_test() as pilot:
            await app._show_page("models")
            await pilot.pause()
            assert get_models.call_count == 1
            assert get_models.call_args.kwargs == {"refresh": False}

            search = app.query_one("#model-search", Input)
            search.focus()
            for key in "visible":
                await pilot.press(key)
            await pilot.pause(0.2)

            assert app.model_search == "visible"
            assert get_models.call_count == 1
            assert len(app.query("#model-list ModelToggleButton")) == 1

            await app.action_refresh()
            await pilot.pause()
            assert get_models.call_count == 2
            assert get_models.call_args.kwargs == {"refresh": True}


@pytest.mark.asyncio
async def test_models_page_shows_recoverable_empty_state() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    with patch(
        "free_claude_code.cli.control_tui.get_models",
        return_value={
            "models": [],
            "catalog_models": [],
            "model_labels": {},
            "catalog_model_labels": {},
            "model_evidence": {},
            "catalog_model_evidence": {},
        },
    ):
        async with app.run_test() as pilot:
            await app._show_page("models")
            await pilot.pause()

            empty = app.query_one("#model-empty", Static)
            assert "Press Refresh" in str(empty.content)
            assert app.query_one("#model-select", Button).disabled
            assert app.query_one("#models-enable", Button).disabled
            assert app.selected_model is None


@pytest.mark.asyncio
async def test_models_page_keeps_configured_provider_visible_before_discovery() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    catalog = {
        "models": ["open_router/existing-model"],
        "catalog_models": ["open_router/existing-model"],
        "model_labels": {},
        "catalog_model_labels": {},
        "model_evidence": {},
        "catalog_model_evidence": {},
        "provider_status": [
            {
                "provider_id": "bai",
                "display_name": "B.AI",
                "kind": "remote",
                "status": "configured",
                "label": "Configured",
            }
        ],
    }
    with patch("free_claude_code.cli.control_tui.get_models", return_value=catalog):
        async with app.run_test() as pilot:
            await app._show_page("models")
            await pilot.pause()

            assert ("B.AI (Configured)", "bai") in app._model_provider_options

            app.model_provider_filter = "bai"
            await app._show_page("models", force=True, focus_target="#model-provider")
            await pilot.pause()

            empty = app.query_one("#model-empty", Static)
            assert "No models cached for B.AI (Configured)" in str(empty.content)
            assert "Press Refresh" in str(empty.content)


@pytest.mark.asyncio
async def test_models_page_use_model_works_after_search_focus_moves_to_action() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    model_a = "open_router/provider/alpha"
    model_b = "open_router/provider/beta"
    catalog = {
        "models": [model_a, model_b],
        "catalog_models": [model_a, model_b],
        "model_labels": {},
        "catalog_model_labels": {},
        "model_evidence": {},
        "catalog_model_evidence": {},
    }
    with (
        patch("free_claude_code.cli.control_tui.get_models", return_value=catalog),
        patch(
            "free_claude_code.cli.control_tui.apply_admin_values",
            return_value={"applied": True},
        ) as apply,
    ):
        async with app.run_test() as pilot:
            await app._show_page("models")
            await pilot.pause()
            search = app.query_one("#model-search", Input)
            search.value = "beta"
            await pilot.pause(0.2)
            assert app.selected_model == model_b

            await pilot.click(app.query_one("#model-select", Button))
            await pilot.pause()

    assert apply.call_args.args[1] == {"MODEL": model_b}


@pytest.mark.asyncio
async def test_models_page_bulk_disable_reuses_cached_discovery() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    app.settings.model_catalog_mode = ModelCatalogMode.ALL
    app.settings.model_catalog_allowlist = "*"
    selected = "open_router/provider/selected"
    retained = "open_router/provider/retained"
    catalog = {
        "models": [selected, retained],
        "catalog_models": [selected, retained],
        "model_labels": {},
        "catalog_model_labels": {},
        "model_evidence": {},
        "catalog_model_evidence": {},
    }
    with (
        patch(
            "free_claude_code.cli.control_tui.get_models", return_value=catalog
        ) as get_models,
        patch(
            "free_claude_code.cli.control_tui.apply_admin_values",
            return_value={"applied": True},
        ) as apply,
    ):
        async with app.run_test() as pilot:
            await app._show_page("models")
            await pilot.pause()
            app.selected_models.add(selected)
            await app.disable_selected_models()
            await pilot.pause()

    assert get_models.call_count == 1
    assert apply.call_args.args[1] == {
        "MODEL_CATALOG_MODE": "curated",
        "MODEL_CATALOG_ALLOWLIST": retained,
    }


@pytest.mark.asyncio
async def test_models_page_rows_are_full_width_click_targets() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    model = "open_router/clickable-model"
    catalog = {
        "models": [model],
        "catalog_models": [model],
        "model_labels": {},
        "catalog_model_labels": {},
        "model_evidence": {},
        "catalog_model_evidence": {},
    }
    with patch("free_claude_code.cli.control_tui.get_models", return_value=catalog):
        async with app.run_test() as pilot:
            await app._show_page("models")
            await pilot.pause()
            model_list = app.query_one("#model-list", VerticalScroll)
            row = model_list.query_one(ModelToggleButton)
            await pilot.click(row, offset=(15, 1))
            await pilot.pause()

            assert app.selected_models == {model}
            assert row.has_class("model-row-pending")


@pytest.mark.asyncio
async def test_models_page_arrow_navigation_moves_between_rows() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    models = ["open_router/first", "open_router/second"]
    catalog = {
        "models": models,
        "catalog_models": models,
        "model_labels": {},
        "catalog_model_labels": {},
        "model_evidence": {},
        "catalog_model_evidence": {},
    }
    with patch("free_claude_code.cli.control_tui.get_models", return_value=catalog):
        async with app.run_test() as pilot:
            await app._show_page("models")
            await pilot.pause()
            rows = list(app.query("#model-list ModelToggleButton"))
            assert app.focused is rows[0]

            await pilot.press("down")
            await pilot.pause()
            assert app.focused is rows[1]
            await pilot.press("space")
            await pilot.pause()
            assert app.selected_models == {models[1]}

            await pilot.press("up")
            await pilot.pause()
            assert app.focused is rows[0]


@pytest.mark.asyncio
async def test_models_page_use_model_follows_visible_highlight_not_stale_selection() -> (
    None
):
    app = ControlCenterApp(_settings(), supervisor=None)
    model_a = "opencode_zen/a"
    model_b = "opencode_zen/b"
    catalog = {
        "models": [model_a, model_b],
        "catalog_models": [model_a, model_b],
        "model_labels": {},
        "catalog_model_labels": {},
        "model_evidence": {},
        "catalog_model_evidence": {},
    }
    with (
        patch("free_claude_code.cli.control_tui.get_models", return_value=catalog),
        patch(
            "free_claude_code.cli.control_tui.apply_admin_values",
            return_value={"applied": True},
        ) as apply,
    ):
        async with app.run_test() as pilot:
            await app._show_page("models")
            await pilot.pause()
            model_list = app.query_one("#model-list", VerticalScroll)
            rows = list(model_list.query(ModelToggleButton))
            rows[0].focus()
            app.selected_model = model_a
            rows[1].focus()
            await pilot.pause()
            await app.model_select()
            await pilot.pause()

    assert apply.call_args.args[1] == {"MODEL": model_b}


@pytest.mark.asyncio
async def test_profiles_page_exposes_creation_and_selects_new_profile() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    with (
        patch(
            "free_claude_code.cli.control_tui.list_profiles",
            return_value=("default",),
        ),
        patch(
            "free_claude_code.cli.control_tui.create_profile",
            return_value="research",
        ) as create,
    ):
        async with app.run_test() as pilot:
            await app._show_page("profiles")
            await pilot.pause()
            assert app.query_one("#profile-create")

            await app._create_profile("research")
            await pilot.pause()

    create.assert_called_once_with("research")
    assert app.next_profile == "research"


@pytest.mark.asyncio
async def test_control_tui_keeps_render_failures_visible() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    with patch(
        "free_claude_code.cli.control_tui.get_usage",
        side_effect=RuntimeError("usage backend is unavailable"),
    ):
        async with app.run_test() as pilot:
            await app._show_page("usage")
            await pilot.pause()

            summary = str(app.query_one("#summary", Static).content)
            assert summary == "Usage unavailable: usage backend is unavailable"


@pytest.mark.asyncio
async def test_control_tui_keeps_launch_failures_visible_for_retry() -> None:
    app = ControlCenterApp(
        _settings(),
        supervisor=None,
        startup_error=(
            "Could not launch Claude:\n"
            "FCC Claude compatibility firewall blocked launch: Claude Code "
            "version 2.1.250 is quarantined for FCC.\n"
            "Exit status: 78."
        ),
    )
    with (
        patch(
            "free_claude_code.cli.control_tui.fcc_provider_account_summary",
            return_value="fcc@example.com",
        ),
        patch(
            "free_claude_code.cli.control_tui.codex_accounts.active_account_summary",
            return_value="codex@example.com (profile personal)",
        ),
    ):
        async with app.run_test() as pilot:
            await pilot.pause()

            summary = str(app.query_one("#summary", Static).content)
            error_card = app.query_one(".launch-error-card", Static)

            assert "Launch failed safely" in summary
            assert "version 2.1.250 is quarantined" in str(error_card.content)
            assert "Exit status: 78." in str(error_card.content)
            assert app.query_one("#launch-claude")
            assert app.query_one("#launch-danger")
            assert app.query_one("#launch-retry-claude")
            assert app.query_one("#launch-retry-danger")


@pytest.mark.asyncio
async def test_provider_detail_failures_keep_a_back_action_available() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    with patch(
        "free_claude_code.cli.control_tui.get_admin_config",
        side_effect=RuntimeError("admin endpoint is unavailable"),
    ):
        async with app.run_test() as pilot:
            await app._show_provider_detail("openai")
            await pilot.pause()

            summary = str(app.query_one("#summary", Static).content)
            assert summary == (
                "Provider details unavailable: admin endpoint is unavailable"
            )
            assert app.query_one("#provider-back")


@pytest.mark.asyncio
async def test_repo_selection_is_canonicalized_and_saved_with_account_scope(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    repo = RepoEntry("checkout", str(checkout), "main", "acme/checkout")
    app = ControlCenterApp(_settings(), supervisor=None)
    app._github_identity_loaded = True
    app._github_user = "acme"
    with (
        patch(
            "free_claude_code.cli.control_tui.cache_path",
            return_value=tmp_path / "repos.json",
        ),
        patch("free_claude_code.cli.control_tui.save_cached_repos") as save,
    ):
        async with app.run_test() as pilot:
            saved = await app._persist_repo_selection(repo)
            await pilot.pause()

    assert saved is True
    assert app.selected_repo is not None
    assert app.selected_repo.path == str(checkout.resolve())
    save.assert_called_once()
    assert save.call_args.kwargs["github_user"] == "acme"


@pytest.mark.asyncio
async def test_repo_selection_reports_cache_failure_without_claiming_persistence(
    tmp_path: Path,
) -> None:
    repo = RepoEntry("checkout", str(tmp_path / "checkout"), "main", "acme/checkout")
    app = ControlCenterApp(_settings(), supervisor=None)
    with (
        patch(
            "free_claude_code.cli.control_tui.cache_path",
            return_value=tmp_path / "repos.json",
        ),
        patch(
            "free_claude_code.cli.control_tui.save_cached_repos",
            side_effect=OSError("read-only cache"),
        ),
    ):
        async with app.run_test() as pilot:
            saved = await app._persist_repo_selection(repo)
            await pilot.pause()

    assert saved is False


@pytest.mark.asyncio
async def test_repository_lookup_failure_keeps_existing_selection(
    tmp_path: Path,
) -> None:
    existing = RepoEntry(
        "existing", str(tmp_path / "existing"), "main", "acme/existing"
    )
    app = ControlCenterApp(_settings(), supervisor=None, selected_repo=existing)
    with patch(
        "free_claude_code.cli.control_tui.repository_from_path",
        side_effect=RuntimeError("git probe failed"),
    ):
        async with app.run_test() as pilot:
            await app._open_repo_path(str(tmp_path / "other"))
            await pilot.pause()

    assert app.selected_repo == existing


@pytest.mark.asyncio
async def test_settings_editor_rejects_malformed_field_manifest() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    with patch("free_claude_code.cli.control_tui.get_admin_config", return_value=[]):
        async with app.run_test() as pilot:
            await app._show_page("settings")
            await pilot.pause()
            await app.setting_edit()
            await pilot.pause()

    assert app.page == "settings"


@pytest.mark.asyncio
async def test_provider_editor_accepts_mapping_field_manifest() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    config = {
        "provider_status": [
            {
                "provider_id": "nvidia_nim",
                "display_name": "NVIDIA NIM",
                "kind": "api_key",
            }
        ],
        "fields": (
            {
                "key": "NVIDIA_NIM_API_KEY",
                "label": "NVIDIA NIM API Key",
                "secret": True,
                "configured": False,
            },
        ),
    }
    with patch(
        "free_claude_code.cli.control_tui.get_admin_config", return_value=config
    ):
        async with app.run_test() as pilot:
            await app._show_provider_detail("nvidia_nim")
            await pilot.pause()

            assert app.query_one("#provider-field-edit", Button)


@pytest.mark.asyncio
async def test_unknown_oauth_state_stops_polling() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    app._oauth_provider = "openai"
    with patch(
        "free_claude_code.cli.control_tui.connected_account_status",
        return_value={"state": "expired", "message": "login expired"},
    ):
        async with app.run_test() as pilot:
            await app._poll_live_state()
            await pilot.pause()

    assert app._oauth_provider is None


@pytest.mark.asyncio
async def test_malformed_policy_response_becomes_recoverable_page() -> None:
    app = ControlCenterApp(_settings(), supervisor=None)
    with patch("free_claude_code.cli.control_tui.get_admin_status", return_value=[]):
        async with app.run_test() as pilot:
            await app._show_page("policy")
            await pilot.pause()

            assert "Policy unavailable" in str(
                app.query_one("#summary", Static).content
            )
