"""GUI-like model editing for the Textual control center.

The original model page exposes a powerful catalog, but it asks users to reason
about a temporary bulk selection and then choose a separate enable/disable
operation. This module keeps the existing discovery/filtering backend while
presenting model state like a small settings GUI: click a model to make it the
default, click its access button to enable/disable it, then save all edits once.
"""

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path

from textual import on
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, DataTable, Static

from free_claude_code.cli.commands import ServerSupervisor
from free_claude_code.cli.local_admin import LocalAdminError, apply_admin_values
from free_claude_code.config.model_catalog import ModelCatalogMode
from free_claude_code.config.settings import Settings, get_settings
from free_claude_code.core.diagnostics import format_user_error_preview
from free_claude_code.learning.config import configured_profile

from .control_tui import (
    ControlCenterApp,
    ModelToggleButton,
    _format_launch_failure,
    _model_catalog_effective_models,
    _model_catalog_mode,
    _model_price_label,
)
from .repo_picker import RepoEntry


class ModelDefaultButton(Button):
    """Large click target that behaves like a GUI radio choice for the default."""

    def __init__(
        self,
        model_ref: str,
        row_label: str,
        *,
        is_default: bool,
    ) -> None:
        self.model_ref = model_ref
        self._row_label = row_label
        self._is_default = is_default
        super().__init__(self._render_label(), classes="model-default-button")
        self.set_class(is_default, "model-default-pending")

    def _render_label(self) -> str:
        marker = "● DEFAULT" if self._is_default else "○"
        return f"{marker}   {self._row_label}"

    def set_default(self, is_default: bool) -> None:
        self._is_default = is_default
        self.label = self._render_label()
        self.set_class(is_default, "model-default-pending")


class ModelAccessButton(Button):
    """Direct enabled/disabled toggle for one discovered model."""

    def __init__(
        self,
        model_ref: str,
        *,
        enabled: bool,
        locked_default: bool,
    ) -> None:
        self.model_ref = model_ref
        self._enabled = enabled
        super().__init__(
            self._render_label(),
            classes="model-access-button",
            disabled=locked_default,
        )
        self.set_class(enabled, "model-access-enabled")

    def _render_label(self) -> str:
        return "✓ Enabled" if self._enabled else "○ Disabled"

    def set_enabled(self, enabled: bool, *, locked_default: bool) -> None:
        self._enabled = enabled
        self.label = self._render_label()
        self.disabled = locked_default
        self.set_class(enabled, "model-access-enabled")


class GuiModelControlCenterApp(ControlCenterApp):
    """Control center with an explicit, save-once model settings editor."""

    CSS = (
        ControlCenterApp.CSS
        + """

    #model-list .model-card {
        width: 1fr;
        height: 3;
        min-height: 3;
        margin: 0 0 1 0;
        background: $surface;
    }

    #model-list .model-default-button {
        width: 1fr;
        height: 3;
        min-height: 3;
        margin: 0;
        padding: 0 1;
        text-align: left;
        content-align: left middle;
        border: none;
        background: $surface;
    }

    #model-list .model-default-button:focus {
        background: $primary-darken-2;
        text-style: bold;
    }

    #model-list .model-default-button.model-default-pending {
        color: $text-success;
        background: $success-darken-3;
        text-style: bold;
    }

    #model-list .model-access-button {
        width: 16;
        min-width: 16;
        height: 3;
        min-height: 3;
        margin: 0 0 0 1;
        border: none;
        background: $panel;
    }

    #model-list .model-access-button.model-access-enabled {
        color: $text-success;
    }

    #model-list .model-access-button:focus {
        background: $primary-darken-2;
        text-style: bold;
    }
    """
    )

    def __init__(
        self,
        settings: Settings,
        *,
        supervisor: ServerSupervisor | None,
        selected_repo: RepoEntry | None = None,
        next_profile: str | None = None,
        startup_error: str | None = None,
    ) -> None:
        super().__init__(
            settings,
            supervisor=supervisor,
            selected_repo=selected_repo,
            next_profile=next_profile,
            startup_error=startup_error,
        )
        self._model_editor_loaded = False
        self._model_initial_default: str | None = settings.model
        self._model_pending_default: str | None = settings.model
        self._model_initial_enabled: set[str] = set()
        self._model_pending_enabled: set[str] = set()
        self._model_known_refs: set[str] = set()
        self._model_visible_refs: tuple[str, ...] = ()
        self._model_editor_total = 0
        self._model_editor_policy = "legacy"

    async def _show_page(
        self,
        page: str,
        *,
        force: bool = False,
        focus_target: str | None = None,
        refresh_models: bool = False,
        refresh_repos: bool = False,
    ) -> None:
        await super()._show_page(
            page,
            force=force,
            focus_target=focus_target,
            refresh_models=refresh_models,
            refresh_repos=refresh_repos,
        )
        if page != "models" or focus_target is not None:
            return
        rows = list(self.query("#model-list .model-default-button"))
        if not rows:
            return
        target = next(
            (
                row
                for row in rows
                if isinstance(row, ModelDefaultButton)
                and row.model_ref == self._model_pending_default
            ),
            rows[0],
        )
        target.focus()

    async def _render_models(self, table: DataTable, *, refresh: bool = False) -> None:
        """Reuse discovery/filtering, then replace bulk-selection rows with cards."""

        await super()._render_models(table, refresh=refresh)
        result = await self._load_model_catalog()
        model_list = self.query_one("#model-list", VerticalScroll)
        filtered_refs = tuple(
            row.model_ref for row in model_list.query(ModelToggleButton)
        )

        visible_models = result.get("models")
        visible_refs = (
            {str(raw) for raw in visible_models if raw is not None}
            if isinstance(visible_models, list)
            else set()
        )
        catalog_models = result.get("catalog_models")
        model_refs = (
            {str(raw) for raw in catalog_models if raw is not None}
            if isinstance(catalog_models, list)
            else set(visible_refs)
        )
        effective_models = _model_catalog_effective_models(
            self.settings,
            model_refs,
            legacy_visible_models=visible_refs,
        )
        self._sync_model_editor_state(model_refs, effective_models)
        self._model_visible_refs = filtered_refs
        self._model_editor_total = len(model_refs)
        mode = _model_catalog_mode(self.settings)
        self._model_editor_policy = mode.value if mode is not None else "legacy"

        labels = result.get("catalog_model_labels", result.get("model_labels"))
        evidence = result.get("catalog_model_evidence", result.get("model_evidence"))

        await model_list.remove_children()
        for model in filtered_refs:
            friendly = model
            if isinstance(labels, dict) and isinstance(labels.get(model), str):
                friendly = str(labels[model])
            source = "unknown"
            if isinstance(evidence, dict) and isinstance(evidence.get(model), dict):
                source = str(evidence[model].get("evidence_source", "unknown"))
            price = _model_price_label(model, evidence)
            detail = friendly if friendly == model else f"{friendly}  ·  {model}"
            row_label = f"{price}   {detail}   ·   {source}"
            await model_list.mount(
                Horizontal(
                    ModelDefaultButton(
                        model,
                        row_label,
                        is_default=model == self._model_pending_default,
                    ),
                    ModelAccessButton(
                        model,
                        enabled=model in self._model_pending_enabled,
                        locked_default=model == self._model_pending_default,
                    ),
                    classes="model-card",
                )
            )

        if not filtered_refs:
            empty_message = (
                "No models discovered. Press Refresh to query configured providers."
                if not model_refs
                else "No models match these filters. Clear search or broaden the filters."
            )
            await model_list.mount(
                Static(empty_message, id="model-empty", classes="model-empty")
            )

        self.selected_models.clear()
        self.selected_model = self._model_pending_default
        await self._clear_actions()
        await self._add_action(
            "models-save",
            "Save changes",
            disabled=not self._model_editor_dirty(),
        )
        await self._add_action(
            "models-discard",
            "Discard",
            disabled=not self._model_editor_dirty(),
        )
        await self._add_action("refresh", "Refresh")
        self._update_model_editor_summary()

    def _sync_model_editor_state(
        self,
        model_refs: set[str],
        effective_models: set[str],
    ) -> None:
        """Initialize once and preserve unsaved edits across filters/refreshes."""

        if not self._model_editor_loaded:
            self._model_initial_default = self.settings.model
            self._model_pending_default = self.settings.model
            self._model_initial_enabled = set(effective_models)
            self._model_pending_enabled = set(effective_models)
            if self._model_pending_default in model_refs:
                self._model_initial_enabled.add(self._model_pending_default)
                self._model_pending_enabled.add(self._model_pending_default)
            self._model_known_refs = set(model_refs)
            self._model_editor_loaded = True
            return

        removed = self._model_known_refs - model_refs
        added = model_refs - self._model_known_refs
        self._model_initial_enabled.difference_update(removed)
        self._model_pending_enabled.difference_update(removed)
        self._model_initial_enabled.update(added.intersection(effective_models))
        self._model_pending_enabled.update(added.intersection(effective_models))
        self._model_known_refs = set(model_refs)

        if self._model_pending_default not in model_refs:
            fallback = (
                self.settings.model
                if self.settings.model in model_refs
                else next(iter(sorted(model_refs, key=str.casefold)), None)
            )
            self._model_pending_default = fallback
            if fallback is not None:
                self._model_pending_enabled.add(fallback)

    def _model_editor_dirty(self) -> bool:
        return (
            self._model_pending_default != self._model_initial_default
            or self._model_pending_enabled != self._model_initial_enabled
        )

    def _update_model_editor_summary(self) -> None:
        default = self._model_pending_default or "(none)"
        changes = len(self._model_pending_enabled ^ self._model_initial_enabled)
        if self._model_pending_default != self._model_initial_default:
            changes += 1
        self._model_summary_text = (
            f"Default: {default}   |   Enabled: {len(self._model_pending_enabled)}/"
            f"{self._model_editor_total}   |   Policy: {self._model_editor_policy}   |   "
            f"Unsaved changes: {changes}   |   Showing: "
            f"{len(self._model_visible_refs)}/{self._model_editor_total}\n"
            "Click a model name to make it the default. Click Enabled/Disabled to "
            "change access. The default stays enabled. Press Save changes once when done."
        )
        self.query_one("#summary", Static).update(self._model_summary_text)
        dirty = self._model_editor_dirty()
        self.query_one("#models-save", Button).disabled = not dirty
        self.query_one("#models-discard", Button).disabled = not dirty

    def _refresh_model_editor_widgets(self) -> None:
        for button in self.query("#model-list .model-default-button"):
            if isinstance(button, ModelDefaultButton):
                button.set_default(button.model_ref == self._model_pending_default)
        for button in self.query("#model-list .model-access-button"):
            if isinstance(button, ModelAccessButton):
                button.set_enabled(
                    button.model_ref in self._model_pending_enabled,
                    locked_default=button.model_ref == self._model_pending_default,
                )
        self._update_model_editor_summary()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle model-card controls without selector-dependent dispatch."""

        button = event.button
        if isinstance(button, ModelDefaultButton):
            model = button.model_ref
            self._model_pending_default = model
            self._model_pending_enabled.add(model)
            self.selected_model = model
            self._refresh_model_editor_widgets()
            return
        if not isinstance(button, ModelAccessButton):
            return
        model = button.model_ref
        if model == self._model_pending_default:
            self.notify(
                "The default model must stay enabled. Choose another default first.",
                severity="warning",
            )
            return
        if model in self._model_pending_enabled:
            self._model_pending_enabled.remove(model)
        else:
            self._model_pending_enabled.add(model)
        self._refresh_model_editor_widgets()

    @on(Button.Pressed, "#models-discard")
    def discard_model_changes(self) -> None:
        self._model_pending_default = self._model_initial_default
        self._model_pending_enabled = set(self._model_initial_enabled)
        if self._model_pending_default is not None:
            self._model_pending_enabled.add(self._model_pending_default)
        self.selected_model = self._model_pending_default
        self._refresh_model_editor_widgets()
        self.notify("Discarded model changes.")

    @on(Button.Pressed, "#models-save")
    async def save_model_changes(self) -> None:
        values: dict[str, str] = {}
        if (
            self._model_pending_default is not None
            and self._model_pending_default != self._model_initial_default
        ):
            values["MODEL"] = self._model_pending_default
        if self._model_pending_enabled != self._model_initial_enabled:
            values["MODEL_CATALOG_MODE"] = ModelCatalogMode.CURATED.value
            values["MODEL_CATALOG_ALLOWLIST"] = ", ".join(
                sorted(self._model_pending_enabled, key=str.casefold)
            )
        if not values:
            self.notify("No model changes to save.")
            return

        try:
            result = await asyncio.to_thread(
                apply_admin_values,
                self.settings,
                values,
            )
        except LocalAdminError as exc:
            self.notify(str(exc), title="Model save failed", severity="error")
            return
        except Exception as exc:
            self.notify(
                format_user_error_preview(exc, max_len=240),
                title="Model save failed",
                severity="error",
            )
            return
        if result.get("applied") is not True:
            self.notify("Model changes were rejected.", severity="error")
            return

        get_settings.cache_clear()
        if "MODEL" in values:
            self.settings.model = values["MODEL"]
        if "MODEL_CATALOG_MODE" in values:
            self.settings.model_catalog_mode = ModelCatalogMode.CURATED
            self.settings.model_catalog_allowlist = values["MODEL_CATALOG_ALLOWLIST"]
        self._model_editor_loaded = False
        self.selected_models.clear()
        self.notify("Saved model settings.")
        await self._show_page("models", force=True)


def run_control_tui(
    settings: Settings,
    *,
    supervisor: ServerSupervisor | None,
    launch_client: Callable[[bool, Sequence[str], Path | None], None],
    startup_error: str | None = None,
) -> None:
    """Run the control center with the GUI-like model settings editor."""

    selected_repo: RepoEntry | None = None
    server_profile = configured_profile()
    next_profile = server_profile
    while True:
        result = GuiModelControlCenterApp(
            settings,
            supervisor=supervisor,
            selected_repo=selected_repo,
            next_profile=next_profile,
            startup_error=startup_error,
        ).run()
        startup_error = None
        if result is None or result.action == "quit":
            return
        selected_repo = result.repo
        next_profile = result.profile or next_profile
        if result.action == "launch":
            argv: tuple[str, ...] = ()
            if next_profile != server_profile:
                argv = ("--profile", next_profile)
            try:
                launch_client(
                    result.danger,
                    argv,
                    Path(selected_repo.path) if selected_repo is not None else None,
                )
            except SystemExit as exc:
                failure = _format_launch_failure(exc)
                if failure is None:
                    continue
                startup_error = failure
            except Exception as exc:
                startup_error = _format_launch_failure(exc)
            continue
