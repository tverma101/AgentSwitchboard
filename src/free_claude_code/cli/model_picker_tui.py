"""Mouse-first desktop-style control center and model editor.

The shell and interaction hierarchy are adapted from tuiui's terminal desktop
patterns (jaylfc/tuiui, MIT, pinned in THIRD_PARTY_NOTICES.md): compact desktop
chrome, launcher-like navigation, window/panel hierarchy, dense list + inspector
workflows, and mouse-first settings controls. AgentSwitchboard keeps its existing
Textual runtime and all existing provider/admin backends; no tuiui daemon, PTY
host, remote-session stack, or file-manager runtime is embedded here.
"""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    OptionList,
    Select,
    Static,
)
from textual.widgets.option_list import Option

from free_claude_code.cli.commands import ServerSupervisor
from free_claude_code.cli.local_admin import LocalAdminError, apply_admin_values
from free_claude_code.config.model_catalog import ModelCatalogMode
from free_claude_code.config.settings import Settings
from free_claude_code.core.diagnostics import format_user_error_preview
from free_claude_code.learning.config import configured_profile

from .control_tui import (
    ControlCenterApp,
    ModelToggleButton,
    _catalog_model_refs,
    _format_launch_failure,
    _model_catalog_effective_models,
    _model_catalog_mode,
    _model_empty_message,
    _model_price_label,
    _model_provider_id,
    _model_provider_options,
    _model_rows,
)
from .repo_picker import RepoEntry


def _clip(value: str, limit: int) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip() + "…"


class ModelListButton(Button):
    """One compact, Finder-style model row."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("enter", "press", "Inspect model", show=False),
        Binding("space", "press", "Inspect model", show=False),
        Binding("up", "focus_previous_model", "Previous model", show=False),
        Binding("down", "focus_next_model", "Next model", show=False),
    ]

    def __init__(
        self,
        model_ref: str,
        friendly: str,
        *,
        price: str,
        is_default: bool,
        enabled: bool,
        selected: bool,
    ) -> None:
        self.model_ref = model_ref
        self.friendly = friendly
        self.price = price
        self._is_default = is_default
        self._enabled = enabled
        self._selected = selected
        super().__init__(self._render_label(), classes="model-list-row")
        self._apply_classes()

    def _render_label(self) -> str:
        default_mark = "★" if self._is_default else " "
        access_mark = "✓" if self._enabled else "○"
        provider = _clip(_model_provider_id(self.model_ref).replace("_", " "), 13)
        name = _clip(self.friendly, 48)
        return f"{default_mark} {access_mark}  {self.price:<6}  {name:<48}  {provider}"

    def _apply_classes(self) -> None:
        self.set_class(self._is_default, "model-row-default")
        self.set_class(self._enabled, "model-row-enabled")
        self.set_class(self._selected, "model-row-selected")

    def set_state(self, *, is_default: bool, enabled: bool, selected: bool) -> None:
        self._is_default = is_default
        self._enabled = enabled
        self._selected = selected
        self.label = self._render_label()
        self._apply_classes()

    def _focus_sibling(self, direction: int) -> None:
        parent = self.parent
        if parent is None:
            return
        rows = list(parent.query(ModelListButton))
        try:
            index = rows.index(self)
        except ValueError:
            return
        next_index = index + direction
        if 0 <= next_index < len(rows):
            rows[next_index].focus()

    def action_focus_previous_model(self) -> None:
        self._focus_sibling(-1)

    def action_focus_next_model(self) -> None:
        self._focus_sibling(1)


class TuiuiControlCenterApp(ControlCenterApp):
    """Desktop-like shell over the existing AgentSwitchboard control actions."""

    CSS = (
        ControlCenterApp.CSS
        + """

    Screen {
        background: $background;
    }

    Header {
        height: 1;
        background: $panel;
        color: $text;
    }

    #shell {
        height: 1fr;
        padding: 1 1 0 1;
        background: $background;
    }

    #sidebar {
        width: 22;
        min-width: 20;
        margin-right: 1;
        border: round $panel-lighten-1;
        background: $surface;
    }

    #sidebar:focus-within {
        border: round $primary-darken-1;
    }

    #sidebar-title {
        height: 3;
        padding: 1 1 0 2;
        color: $text;
        text-style: bold;
        background: $surface;
    }

    #nav {
        height: 1fr;
        padding: 0 1;
        background: $surface;
    }

    #launch-row {
        height: 3;
        padding: 0 1;
        background: $surface;
    }

    #launch-row Button {
        height: 3;
        min-width: 8;
        border: none;
        margin: 0;
    }

    #main-panel {
        width: 1fr;
        border: round $panel-lighten-1;
        background: $surface;
    }

    #main-panel:focus-within {
        border: round $primary-darken-1;
    }

    #window-titlebar {
        height: 3;
        min-height: 3;
        padding: 0 1;
        background: $panel;
    }

    #page-title {
        width: 1fr;
        height: 3;
        padding: 1 0 0 1;
        color: $text;
        text-style: bold;
    }

    #window-state {
        width: auto;
        height: 3;
        padding: 1 1 0 0;
        color: $text-muted;
    }

    #summary {
        height: auto;
        min-height: 1;
        max-height: 5;
        padding: 1 2;
        color: $text-muted;
        background: $surface;
    }

    #model-toolbar {
        height: 3;
        min-height: 3;
        padding: 0 1;
        background: $surface;
    }

    #model-provider {
        width: 24;
        margin-right: 1;
    }

    #model-price {
        width: 16;
        margin-right: 1;
    }

    #model-search {
        width: 1fr;
    }

    #model-workspace {
        height: 1fr;
        margin: 0 1;
        background: $surface;
    }

    #model-browser {
        width: 1fr;
        height: 1fr;
        border: round $panel-lighten-1;
        background: $background;
    }

    #model-browser-title {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: $panel;
    }

    #model-list {
        height: 1fr;
        margin: 0;
        padding: 0;
        background: $background;
        border: none;
    }

    #model-list .model-list-row {
        width: 1fr;
        height: 1;
        min-height: 1;
        margin: 0;
        padding: 0 1;
        border: none;
        text-align: left;
        content-align: left middle;
        background: $background;
        color: $text-muted;
    }

    #model-list .model-list-row:hover,
    #model-list .model-list-row:focus,
    #model-list .model-list-row.model-row-selected {
        background: $primary-darken-3;
        color: $text;
        text-style: bold;
    }

    #model-list .model-list-row.model-row-enabled {
        color: $text;
    }

    #model-list .model-list-row.model-row-default {
        color: $text-success;
        text-style: bold;
    }

    #model-list .model-empty {
        height: auto;
        padding: 1 2;
        color: $text-muted;
        background: $background;
    }

    #model-inspector {
        width: 38;
        min-width: 32;
        height: 1fr;
        margin-left: 1;
        padding: 1 2;
        border: round $panel-lighten-1;
        background: $surface-darken-1;
    }

    #model-inspector-title {
        height: auto;
        min-height: 1;
        color: $text;
        text-style: bold;
    }

    #model-inspector-status {
        height: auto;
        min-height: 1;
        margin-top: 1;
        color: $text-success;
    }

    #model-inspector-meta {
        height: auto;
        min-height: 6;
        margin: 1 0;
        color: $text-muted;
    }

    #model-inspector-hint {
        height: auto;
        min-height: 2;
        margin-top: 1;
        color: $text-muted;
    }

    #model-inspector Button {
        width: 1fr;
        height: 3;
        min-height: 3;
        border: none;
        margin-top: 1;
    }

    #model-toggle-access.model-access-enabled {
        color: $text-warning;
    }

    #actions {
        height: 3;
        min-height: 3;
        padding: 0 1;
        background: $panel;
    }

    #actions Button {
        height: 3;
        min-width: 10;
        border: none;
        margin-right: 1;
    }

    #table,
    #content {
        margin: 0 1;
    }

    Footer {
        height: 1;
        background: $panel;
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
        self._model_inspector_ref: str | None = settings.model
        self._model_labels: dict[str, str] = {}
        self._model_sources: dict[str, str] = {}
        self._model_prices: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        # The header icon opens Textual's command palette, but it is not a
        # useful control in this app's workflow. Keep the header/clock while
        # removing the misleading clickable placeholder.
        yield Header(show_clock=True, icon="")
        with Horizontal(id="shell"):
            with Vertical(id="sidebar"):
                yield Static(self.TITLE, id="sidebar-title")
                yield OptionList(
                    *(Option(label, id=page) for page, label in self.NAV),
                    id="nav",
                )
                with Horizontal(id="launch-row"):
                    yield Button("Claude", id="launch-claude", variant="primary")
                    yield Button("Danger", id="launch-danger", variant="error")
            with Vertical(id="main-panel"):
                with Horizontal(id="window-titlebar"):
                    yield Static("Dashboard", id="page-title")
                    yield Static("Control Center", id="window-state")
                yield Static("", id="summary")
                with Horizontal(id="model-toolbar"):
                    yield Select(
                        [("All providers", "all")],
                        value="all",
                        id="model-provider",
                    )
                    yield Select(
                        [
                            ("Free first", "free-first"),
                            ("Free only", "free-only"),
                            ("All prices", "all"),
                        ],
                        value="free-first",
                        id="model-price",
                    )
                    yield Input(placeholder="Search models…", id="model-search")
                with Horizontal(id="model-workspace"):
                    with Vertical(id="model-browser"):
                        yield Static(
                            "★ default   ✓ enabled   ○ disabled",
                            id="model-browser-title",
                        )
                        yield VerticalScroll(id="model-list")
                    with Vertical(id="model-inspector"):
                        yield Static("Select a model", id="model-inspector-title")
                        yield Static("", id="model-inspector-status")
                        yield Button("★ Make default", id="model-set-default")
                        yield Button("Enable model", id="model-toggle-access")
                        yield Static("", id="model-inspector-meta")
                        yield Static("", id="model-inspector-hint")
                yield DataTable(id="table", cursor_type="row")
                yield VerticalScroll(id="content")
                yield Horizontal(id="actions")
        yield Footer()

    async def _after_page_render(self, page: str, *, focus_target: str | None) -> None:
        workspace = self.query_one("#model-workspace", Horizontal)
        workspace.display = page == "models"
        self.query_one("#window-state", Static).update(
            "Models" if page == "models" else "Control Center"
        )
        if page != "models" or focus_target is not None:
            return
        rows = [
            row
            for row in _model_rows(self.query_one("#model-list", VerticalScroll))
            if isinstance(row, ModelListButton)
        ]
        if not rows:
            return
        target = next(
            (row for row in rows if row.model_ref == self._model_inspector_ref),
            rows[0],
        )
        target.focus()

    async def _render_models(self, table: DataTable, *, refresh: bool = False) -> None:
        """Reuse discovery/filtering, then render a dense browser + inspector."""

        await super()._render_models(table, refresh=refresh)
        result = await self._load_model_catalog()
        model_list = self.query_one("#model-list", VerticalScroll)
        filtered_refs = tuple(
            row.model_ref
            for row in _model_rows(model_list)
            if isinstance(row, ModelToggleButton)
        )

        visible_refs, model_refs = _catalog_model_refs(result)
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
        self._model_labels = {}
        self._model_sources = {}
        self._model_prices = {}
        for model in model_refs:
            friendly = model
            if isinstance(labels, Mapping) and isinstance(labels.get(model), str):
                friendly = str(labels[model])
            source = "unknown"
            if isinstance(evidence, Mapping) and isinstance(
                evidence.get(model), Mapping
            ):
                source = str(evidence[model].get("evidence_source", "unknown"))
            self._model_labels[model] = friendly
            self._model_sources[model] = source
            self._model_prices[model] = _model_price_label(model, evidence)

        if self._model_inspector_ref not in model_refs:
            self._model_inspector_ref = (
                self._model_pending_default
                if self._model_pending_default in model_refs
                else next(iter(filtered_refs), None)
            )

        await model_list.remove_children()
        rows = [
            ModelListButton(
                model,
                self._model_labels.get(model, model),
                price=self._model_prices.get(model, "PRICE?"),
                is_default=model == self._model_pending_default,
                enabled=model in self._model_pending_enabled,
                selected=model == self._model_inspector_ref,
            )
            for model in filtered_refs
        ]
        if rows:
            await model_list.mount(*rows)

        if not filtered_refs:
            await model_list.mount(
                Static(
                    _model_empty_message(
                        _model_provider_options(result, model_refs),
                        self.model_provider_filter,
                        model_refs,
                    ),
                    id="model-empty",
                    classes="model-empty",
                )
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
        self._refresh_model_editor_widgets()

    def _sync_model_editor_state(
        self,
        model_refs: set[str],
        effective_models: set[str],
    ) -> None:
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

        changed_enabled = self._model_pending_enabled ^ self._model_initial_enabled
        default_changed = self._model_pending_default != self._model_initial_default
        self._model_initial_default = self.settings.model
        if not default_changed:
            self._model_pending_default = self.settings.model
        self._model_initial_enabled = set(effective_models).intersection(model_refs)
        pending_enabled = set(self._model_initial_enabled)
        for model in changed_enabled.intersection(model_refs):
            if model in self._model_pending_enabled:
                pending_enabled.add(model)
            else:
                pending_enabled.discard(model)
        self._model_pending_enabled = pending_enabled
        if self._model_pending_default in model_refs:
            self._model_initial_enabled.add(self._model_pending_default)
            self._model_pending_enabled.add(self._model_pending_default)
        self._model_known_refs = set(model_refs)

        if self._model_pending_default is None and model_refs:
            fallback = next(iter(sorted(model_refs, key=str.casefold)))
            self._model_pending_default = fallback
            self._model_pending_enabled.add(fallback)

    def _model_editor_dirty(self) -> bool:
        return (
            self._model_pending_default != self._model_initial_default
            or self._model_pending_enabled != self._model_initial_enabled
        )

    def _model_changes_count(self) -> int:
        changes = len(self._model_pending_enabled ^ self._model_initial_enabled)
        if self._model_pending_default != self._model_initial_default:
            changes += 1
        return changes

    def _update_model_editor_summary(self) -> None:
        default = self._model_pending_default or "(none)"
        self._model_summary_text = (
            f"★ {_clip(default, 70)}   •   ✓ {len(self._model_pending_enabled)}/"
            f"{self._model_editor_total} enabled   •   {self._model_editor_policy}   •   "
            f"{self._model_changes_count()} unsaved   •   "
            f"{len(self._model_visible_refs)}/{self._model_editor_total} shown"
        )
        self.query_one("#summary", Static).update(self._model_summary_text)
        dirty = self._model_editor_dirty()
        self.query_one("#models-save", Button).disabled = not dirty
        self.query_one("#models-discard", Button).disabled = not dirty

    def _update_model_inspector(self) -> None:
        model = self._model_inspector_ref
        title = self.query_one("#model-inspector-title", Static)
        status = self.query_one("#model-inspector-status", Static)
        meta = self.query_one("#model-inspector-meta", Static)
        hint = self.query_one("#model-inspector-hint", Static)
        default_button = self.query_one("#model-set-default", Button)
        access_button = self.query_one("#model-toggle-access", Button)

        if model is None or model not in self._model_known_refs:
            title.update("Select a model")
            status.update("")
            meta.update("")
            hint.update("Click a row to inspect it.")
            default_button.disabled = True
            access_button.disabled = True
            access_button.set_class(False, "model-access-enabled")
            return

        is_default = model == self._model_pending_default
        enabled = model in self._model_pending_enabled
        title.update(self._model_labels.get(model, model))
        state = "★ Default" if is_default else "Model"
        access = "✓ Enabled" if enabled else "○ Disabled"
        status.update(f"{state}    {access}")
        meta.update(
            "\n".join(
                (
                    f"Provider   {_model_provider_id(model)}",
                    f"Price      {self._model_prices.get(model, 'PRICE?')}",
                    f"Source     {self._model_sources.get(model, 'unknown')}",
                    "",
                    "Model ref",
                    model,
                )
            )
        )
        if is_default and enabled:
            hint.update(
                f"Disable is allowed: {self.TITLE} will hand default status to "
                "another model automatically."
            )
        elif enabled:
            hint.update("Disable removes this model from the curated catalog on Save.")
        else:
            hint.update("Enable adds this model to the curated catalog on Save.")
        default_button.disabled = is_default
        access_button.disabled = False
        access_button.label = "Disable model" if enabled else "Enable model"
        access_button.set_class(enabled, "model-access-enabled")

    def _refresh_model_editor_widgets(self) -> None:
        for row in self.query(ModelListButton):
            row.set_state(
                is_default=row.model_ref == self._model_pending_default,
                enabled=row.model_ref in self._model_pending_enabled,
                selected=row.model_ref == self._model_inspector_ref,
            )
        self._update_model_inspector()
        self._update_model_editor_summary()

    def _choose_replacement_default(self, model: str) -> str | None:
        enabled_candidates = sorted(
            self._model_pending_enabled - {model}, key=str.casefold
        )
        if enabled_candidates:
            return enabled_candidates[0]
        known_candidates = sorted(self._model_known_refs - {model}, key=str.casefold)
        return known_candidates[0] if known_candidates else None

    def _toggle_model_access(self, model: str) -> None:
        if model not in self._model_known_refs:
            return
        if model not in self._model_pending_enabled:
            self._model_pending_enabled.add(model)
            self._refresh_model_editor_widgets()
            return

        if model == self._model_pending_default:
            replacement = self._choose_replacement_default(model)
            if replacement is None:
                self.notify(
                    "This is the only discovered model, so it cannot be disabled.",
                    severity="warning",
                )
                return
            self._model_pending_enabled.add(replacement)
            self._model_pending_default = replacement
            self.selected_model = replacement
            self.notify(
                f"Default moved to {self._model_labels.get(replacement, replacement)}."
            )

        self._model_pending_enabled.discard(model)
        self._refresh_model_editor_widgets()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button = event.button
        if not isinstance(button, ModelListButton):
            return
        self._model_inspector_ref = button.model_ref
        self._refresh_model_editor_widgets()

    @on(Button.Pressed, "#model-set-default")
    def make_inspected_model_default(self) -> None:
        model = self._model_inspector_ref
        if model is None:
            return
        self._model_pending_default = model
        self._model_pending_enabled.add(model)
        self.selected_model = model
        self._refresh_model_editor_widgets()

    @on(Button.Pressed, "#model-toggle-access")
    def toggle_inspected_model_access(self) -> None:
        model = self._model_inspector_ref
        if model is not None:
            self._toggle_model_access(model)

    @on(Button.Pressed, "#models-discard")
    def discard_model_changes(self) -> None:
        self._model_pending_default = self._model_initial_default
        self._model_pending_enabled = set(self._model_initial_enabled)
        if self._model_pending_default is not None:
            self._model_pending_enabled.add(self._model_pending_default)
        self.selected_model = self._model_pending_default
        if self._model_pending_default in self._model_known_refs:
            self._model_inspector_ref = self._model_pending_default
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
        if not isinstance(result, Mapping):
            self.notify(
                "Model save returned malformed data.",
                title="Model save failed",
                severity="error",
            )
            return
        if result.get("applied") is not True:
            self.notify("Model changes were rejected.", severity="error")
            return

        self._refresh_settings_snapshot()
        if "MODEL" in values:
            self.settings.model = values["MODEL"]
        if "MODEL_CATALOG_MODE" in values:
            self.settings.model_catalog_mode = ModelCatalogMode.CURATED
            self.settings.model_catalog_allowlist = values["MODEL_CATALOG_ALLOWLIST"]
        self._model_editor_loaded = False
        self.selected_models.clear()
        self.notify("Saved model settings.")
        await self._show_page("models", force=True)


# Compatibility name for callers/tests written against the first GUI-like picker.
GuiModelControlCenterApp = TuiuiControlCenterApp


def run_control_tui(
    settings: Settings,
    *,
    supervisor: ServerSupervisor | None,
    launch_client: Callable[[bool, Sequence[str], Path | None], None],
    startup_error: str | None = None,
) -> None:
    """Run the tuiui-inspired desktop control center."""

    selected_repo: RepoEntry | None = None
    server_profile = configured_profile()
    next_profile = server_profile
    while True:
        app = TuiuiControlCenterApp(
            settings,
            supervisor=supervisor,
            selected_repo=selected_repo,
            next_profile=next_profile,
            startup_error=startup_error,
        )
        result = app.run()
        if isinstance(app.settings, Settings):
            settings = app.settings
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
