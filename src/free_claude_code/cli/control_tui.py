"""Textual control center backed by CodeSwitchyard's existing admin/actions.

UI shell/layout/focus/modal patterns are adapted from Harlequin at
fcfaa6c524a6cd47e17701d931eac0243c8c85b6 (MIT, Ted Conbeer).
See THIRD_PARTY_NOTICES.md. The CodeSwitchyard-specific code in this module is
limited to feeding existing local actions/state into that shell.
"""

import asyncio
import json
import os
import webbrowser
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    Select,
    Static,
)
from textual.widgets.option_list import Option

from free_claude_code.application.account_identity import (
    fcc_provider_account_summary,
)
from free_claude_code.application.connected_accounts import ConnectedAccountLoginMode
from free_claude_code.application.model_metadata import (
    normalize_model_pricing,
    pricing_is_free,
)
from free_claude_code.cli.claude_env import context_cap_tokens
from free_claude_code.cli.commands import ServerStatus, ServerSupervisor
from free_claude_code.cli.local_admin import (
    LocalAdminError,
    apply_admin_values,
    cancel_connected_account_login,
    connected_account_status,
    disconnect_connected_account,
    get_admin_config,
    get_admin_status,
    get_models,
    get_usage,
    route_diagnostic,
    start_connected_account_login,
    test_provider,
)
from free_claude_code.config.model_catalog import (
    ModelCatalogMode,
    ModelCatalogPolicy,
    parse_model_catalog_allowlist,
)
from free_claude_code.config.paths import server_log_path
from free_claude_code.config.provider_catalog import PROVIDER_CATALOG, ProviderAuthKind
from free_claude_code.config.settings import Settings, get_settings
from free_claude_code.core.diagnostics import format_user_error_preview
from free_claude_code.learning.config import (
    LearningProfileError,
    configured_profile,
    create_profile,
    list_profiles,
)
from free_claude_code.learning.reviewer_flow import reviewer_status

from . import codex_accounts
from .harlequin_app_base import HarlequinAppBase
from .repo_picker import (
    RepoEntry,
    cache_is_fresh,
    cache_path,
    deduplicate_repos,
    default_roots,
    discover_repos,
    load_cached_repos,
    repository_from_path,
    save_cached_repos,
)


@dataclass(frozen=True, slots=True)
class ControlResult:
    """One action that must temporarily leave the alternate-screen TUI."""

    action: str
    danger: bool = False
    profile: str | None = None
    repo: RepoEntry | None = None


def _format_launch_failure(exc: BaseException) -> str | None:
    """Build a persistent, redacted control-center message for a launch failure."""

    if isinstance(exc, SystemExit):
        if exc.code in {None, 0}:
            return None
        code = exc.code if isinstance(exc.code, int) else 1
        return (
            "Could not launch Claude:\n"
            f"Claude exited with status {exc.code}.\n"
            f"Exit status: {code}."
        )

    detail = format_user_error_preview(exc, max_len=700)
    exit_code = getattr(exc, "exit_code", None)
    if isinstance(exit_code, int) and exit_code != 0:
        detail = f"{detail}\nExit status: {exit_code}."
    return f"Could not launch Claude:\n{detail}"


class ConfirmModal(ModalScreen[bool]):
    """Harlequin confirm-modal interaction, adapted for CodeSwitchyard."""

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-outer"):
            yield Label(self.prompt, id="modal-prompt")
            with Horizontal(id="modal-buttons"):
                yield Button("No", id="modal-no")
                yield Button("Yes", variant="primary", id="modal-yes")

    @on(Button.Pressed, "#modal-yes")
    def accept(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#modal-no")
    def reject(self) -> None:
        self.dismiss(False)


class InputModal(ModalScreen[str | None]):
    """Small Harlequin-style modal used instead of nested ``input()`` prompts."""

    def __init__(self, title: str, prompt: str, *, secret: bool = False) -> None:
        super().__init__()
        self.title_text = title
        self.prompt = prompt
        self.secret = secret

    def compose(self) -> ComposeResult:
        with Vertical(id="input-outer"):
            yield Label(self.prompt, id="input-label")
            yield Input(password=self.secret, id="input-value")
            with Horizontal(id="input-buttons"):
                yield Button("Cancel", id="input-cancel")
                yield Button("Save", variant="primary", id="input-save")

    def on_mount(self) -> None:
        outer = self.query_one("#input-outer")
        outer.border_title = self.title_text
        self.query_one("#input-value", Input).focus()

    @on(Input.Submitted, "#input-value")
    @on(Button.Pressed, "#input-save")
    def save(self) -> None:
        self.dismiss(self.query_one("#input-value", Input).value.strip() or None)

    @on(Button.Pressed, "#input-cancel")
    def cancel(self) -> None:
        self.dismiss(None)


class ModelToggleButton(Button):
    """A full-row, keyboard-and-mouse-accessible model selection control."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("enter", "press", "Press model", show=False),
        Binding("space", "press", "Toggle model", show=False),
        Binding("up", "focus_previous_model", "Previous model", show=False),
        Binding("down", "focus_next_model", "Next model", show=False),
    ]

    def __init__(self, model_ref: str, row_label: str, *, pending: bool) -> None:
        self.model_ref = model_ref
        self._row_label = row_label
        self._pending = pending
        super().__init__(self._render_label(), classes="model-row")
        self.set_class(pending, "model-row-pending")

    def _render_label(self) -> str:
        marker = "[x]" if self._pending else "[ ]"
        return f"{marker}  {self._row_label}"

    def set_pending(self, pending: bool) -> None:
        """Update the pending marker without replacing the focused row."""

        self._pending = pending
        self.label = self._render_label()
        self.set_class(pending, "model-row-pending")

    def _focus_sibling(self, direction: int) -> None:
        parent = self.parent
        if parent is None:
            return
        rows = list(parent.query(ModelToggleButton))
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


def _configured_model_refs(settings: Settings) -> tuple[str, ...]:
    """Return unique configured routes for the compact model catalog view."""

    refs: list[str] = []
    for attr in ("model", "model_fable", "model_opus", "model_sonnet", "model_haiku"):
        value = getattr(settings, attr, None)
        if not isinstance(value, str):
            continue
        value = value.strip()
        if not value or value.casefold() == "none" or value in refs:
            continue
        refs.append(value)
    return tuple(refs)


def _model_provider_id(model: str) -> str:
    """Return the provider portion used by the model toolbar filter."""

    return model.split("/", 1)[0] if "/" in model else "other"


def _model_price_state(model: str, evidence: Any) -> str:
    """Return ``free``, ``paid``, or ``unknown`` from model evidence.

    A missing price is intentionally unknown. The ``:free`` suffix is used
    only as a provider-declared OpenRouter variant fallback; it is not a
    hardcoded model allowlist.
    """

    record = evidence.get(model) if isinstance(evidence, Mapping) else None
    record = record if isinstance(record, Mapping) else {}
    explicit = record.get("is_free")
    if isinstance(explicit, bool):
        return "free" if explicit else "paid"

    metadata = record.get("catalog_metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    explicit = metadata.get("is_free")
    if isinstance(explicit, bool):
        return "free" if explicit else "paid"

    raw_pricing = record.get("pricing")
    if not isinstance(raw_pricing, Mapping):
        raw_pricing = metadata.get("pricing")
    pricing_status = pricing_is_free(normalize_model_pricing(raw_pricing))
    if pricing_status is not None:
        return "free" if pricing_status else "paid"

    if _model_provider_id(model) == "open_router" and model.casefold().endswith(
        ":free"
    ):
        return "free"
    return "unknown"


def _model_price_label(model: str, evidence: Any) -> str:
    """Return a compact user-facing price evidence label."""

    return {
        "free": "FREE",
        "paid": "PAID",
        "unknown": "PRICE?",
    }[_model_price_state(model, evidence)]


def _model_sort_key(model: str, labels: Any, evidence: Any) -> tuple[int, str, str]:
    """Sort reliable free models first while keeping other rows stable."""

    rank = {"free": 0, "unknown": 1, "paid": 2}[_model_price_state(model, evidence)]
    friendly = labels.get(model) if isinstance(labels, Mapping) else None
    display_name = friendly if isinstance(friendly, str) else model
    return rank, display_name.casefold(), model.casefold()


def _model_catalog_mode(settings: Settings) -> ModelCatalogMode | None:
    """Return a normalized model-catalog mode without changing settings."""

    raw_mode = getattr(settings, "model_catalog_mode", None)
    if raw_mode is None or raw_mode == "":
        return None
    try:
        return (
            raw_mode
            if isinstance(raw_mode, ModelCatalogMode)
            else ModelCatalogMode(str(raw_mode or ModelCatalogMode.CURATED))
        )
    except ValueError:
        return None


def _model_catalog_allowlist(settings: Settings) -> frozenset[str]:
    """Return the normalized explicit model allowlist."""

    raw_allowlist = getattr(settings, "model_catalog_allowlist", "")
    return (
        parse_model_catalog_allowlist(raw_allowlist)
        if isinstance(raw_allowlist, str)
        else frozenset()
    )


def _model_catalog_enabled_models(settings: Settings, models: set[str]) -> set[str]:
    """Return models explicitly enabled by the allowlist.

    Legacy and ``all`` policies describe effective visibility, not a user's
    checkbox selection.  Keeping those concepts separate prevents the picker
    from presenting every discovered row as if the user had selected it.
    """

    allowlist = _model_catalog_allowlist(settings)
    if not allowlist:
        return set()
    policy = ModelCatalogPolicy(
        mode=ModelCatalogMode.CURATED,
        allowlist=allowlist,
    )
    return {
        model for model in models if policy.is_visible(_model_provider_id(model), model)
    }


def _model_catalog_effective_models(
    settings: Settings,
    models: set[str],
    *,
    legacy_visible_models: set[str] | None = None,
) -> set[str]:
    """Return the effective enabled model refs for a catalog operation."""

    mode = _model_catalog_mode(settings)
    allowlist = _model_catalog_allowlist(settings)
    if mode is ModelCatalogMode.ALL:
        return set(models)
    if mode is None and not allowlist:
        return set(legacy_visible_models or models)
    policy = ModelCatalogPolicy(
        mode=ModelCatalogMode.CURATED,
        allowlist=allowlist,
    )
    return {
        model for model in models if policy.is_visible(_model_provider_id(model), model)
    }


class ControlCenterApp(HarlequinAppBase):
    """Persistent GUI-like terminal shell over the existing control actions."""

    TITLE = "CodeSwitchyard"
    SUB_TITLE = "Control Center"
    MODEL_FILTER_DEBOUNCE_SECONDS = 0.08

    CSS = """
    $border-color-nofocus: $panel;
    $border-color-focus: $primary;

    Screen {
        background: $background;
    }

    Header {
        background: $primary-darken-2;
    }

    #shell {
        height: 1fr;
    }

    #sidebar {
        width: 28;
        min-width: 24;
        border: round $border-color-nofocus;
        background: $background;
    }

    #sidebar:focus-within,
    #main-panel:focus-within {
        border: round $border-color-focus;
    }

    #sidebar-title {
        height: 3;
        padding: 1 1 0 1;
        text-style: bold;
        color: $primary;
    }

    #nav {
        height: 1fr;
        padding: 0 1;
        background: $background;
    }

    #launch-row {
        height: 3;
        padding: 0 1;
    }

    #launch-row Button {
        width: 1fr;
        min-width: 8;
        height: 3;
        border: none;
    }

    #main-panel {
        width: 1fr;
        border: round $border-color-nofocus;
        background: $background;
    }

    #page-title {
        height: 3;
        padding: 1 2 0 2;
        text-style: bold;
        color: $primary;
    }

    #summary {
        height: auto;
        min-height: 3;
        padding: 0 2 1 2;
        color: $text-muted;
    }

    .launch-error-card {
        height: auto;
        min-height: 4;
        margin: 0 2 1 2;
        padding: 1 2;
        color: $error;
        border: round $error;
        background: $surface;
    }

    #table {
        height: 1fr;
        margin: 0 1;
        background: $background;
    }

    #model-list {
        height: 1fr;
        margin: 0 1;
        padding: 0 1;
        background: $background;
        border: none;
    }

    #model-list ModelToggleButton {
        width: 1fr;
        height: 3;
        min-height: 3;
        margin: 0 0 1 0;
        padding: 0 1;
        text-align: left;
        content-align: left middle;
        border: none;
        background: $surface;

        &:focus {
            background: $primary-darken-2;
            text-style: bold;
        }
    }

    #model-list ModelToggleButton.model-row-pending {
        color: $text-success;
        background: $success-darken-3;
    }

    #model-list .model-empty {
        height: auto;
        padding: 1 2;
        color: $text-muted;
        background: $surface;
    }

    DataTable > .datatable--header {
        text-style: bold;
        background: $background;
        color: $primary;
    }

    DataTable > .datatable--cursor {
        background: $secondary;
        color: auto;
    }

    #content {
        height: 1fr;
        padding: 0 2;
        background: $background;
    }

    #actions {
        height: 3;
        padding: 0 1;
        background: $background;
    }

    #actions Button {
        width: auto;
        min-width: 10;
        height: 3;
        border: none;
        margin-right: 1;
    }

    #modal-outer,
    #input-outer {
        width: 64;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        border: round $primary;
        background: $background;
        align: center middle;
    }

    ConfirmModal,
    InputModal {
        align: center middle;
        background: $background 70%;
    }

    #modal-buttons,
    #input-buttons {
        height: 3;
        align-horizontal: right;
        margin-top: 1;
    }

    #modal-buttons Button,
    #input-buttons Button {
        width: 12;
        min-width: 10;
        height: 3;
        border: none;
        margin-left: 1;
    }

    #model-toolbar {
        height: 3;
        padding: 0 2;
        background: $background;
    }

    #model-provider {
        width: 28;
        margin-right: 1;
    }

    #model-price {
        width: 18;
        margin-right: 1;
    }

    #model-search {
        width: 1fr;
    }

    #input-value {
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("q", "quit", "Quit"),
        ("c", "launch_claude", "Claude"),
        ("d", "launch_danger", "Danger"),
        ("r", "refresh", "Refresh"),
        ("escape", "dashboard", "Dashboard"),
    ]

    NAV = (
        ("dashboard", "Dashboard"),
        ("providers", "Providers"),
        ("accounts", "Accounts"),
        ("repos", "Repositories"),
        ("profiles", "Profiles"),
        ("models", "Models"),
        ("reviewers", "Reviewers"),
        ("usage", "Usage"),
        ("diagnose", "Diagnose"),
        ("policy", "Policy"),
        ("logs", "Logs"),
        ("settings", "Settings"),
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
        super().__init__()
        self.settings = settings
        self.supervisor = supervisor
        initial_repo = selected_repo or repository_from_path(Path.cwd())
        normalized_repos = (
            deduplicate_repos([initial_repo]) if initial_repo is not None else []
        )
        self.selected_repo = normalized_repos[0] if normalized_repos else None
        self.next_profile = next_profile or configured_profile()
        self.startup_error = startup_error
        self.page = "dashboard"
        self.selected_provider: str | None = None
        self.selected_codex_profile: str | None = None
        self.selected_model: str | None = None
        self.model_search = ""
        self.model_provider_filter = "all"
        self.model_price_filter = "free-first"
        self.selected_models: set[str] = set()
        self._model_provider_options: tuple[tuple[str, str], ...] = ()
        self._updating_model_controls = False
        self._model_summary_text = ""
        self._model_catalog_result: dict[str, Any] | None = None
        self._model_catalog_lock: asyncio.Lock | None = None
        self._model_filter_timer: Timer | None = None
        self._oauth_provider: str | None = None
        self._oauth_last_state: str | None = None
        self._oauth_poll_in_flight = False
        self._oauth_poll_error_notified = False
        self._repo_inventory: tuple[RepoEntry, ...] = ()
        self._repo_inventory_loaded = False
        self._repos: tuple[RepoEntry, ...] = ()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="shell"):
            with Vertical(id="sidebar"):
                yield Static("CodeSwitchyard", id="sidebar-title")
                yield OptionList(
                    *(Option(label, id=page) for page, label in self.NAV),
                    id="nav",
                )
                with Horizontal(id="launch-row"):
                    yield Button("Claude", id="launch-claude", variant="primary")
                    yield Button("Danger", id="launch-danger", variant="error")
            with Vertical(id="main-panel"):
                yield Static("Dashboard", id="page-title")
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
                yield VerticalScroll(id="model-list")
                yield DataTable(id="table", cursor_type="row")
                yield VerticalScroll(id="content")
                yield Horizontal(id="actions")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#model-toolbar", Horizontal).display = False
        self.query_one("#model-list", VerticalScroll).display = False
        self.query_one("#content").display = False
        self.set_interval(1.0, self._poll_live_state)
        if self.startup_error:
            self.notify(self.startup_error, title="Launch failed", severity="error")
        await self._show_page("dashboard")

    @on(OptionList.OptionSelected, "#nav")
    async def select_page(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id
        if option_id is not None:
            await self._show_page(str(option_id))

    @on(Button.Pressed, "#launch-claude")
    def launch_claude_button(self) -> None:
        self.action_launch_claude()

    @on(Button.Pressed, "#launch-danger")
    def launch_danger_button(self) -> None:
        self.action_launch_danger()

    @on(Button.Pressed, "#launch-retry-claude")
    def launch_retry_claude_button(self) -> None:
        """Retry a failed launch through the launcher's recovery path."""

        self.action_launch_claude()

    @on(Button.Pressed, "#launch-retry-danger")
    def launch_retry_danger_button(self) -> None:
        """Retry a failed danger launch through the launcher's recovery path."""

        self.action_launch_danger()

    def action_launch_claude(self) -> None:
        self.exit(
            ControlResult(
                "launch",
                danger=False,
                profile=self.next_profile,
                repo=self.selected_repo,
            )
        )

    def action_launch_danger(self) -> None:
        self.exit(
            ControlResult(
                "launch",
                danger=True,
                profile=self.next_profile,
                repo=self.selected_repo,
            )
        )

    async def action_refresh(self) -> None:
        self._cancel_model_filter_timer()
        await self._show_page(
            self.page,
            force=True,
            refresh_models=self.page == "models",
            refresh_repos=self.page == "repos",
        )

    async def action_dashboard(self) -> None:
        nav = self.query_one("#nav", OptionList)
        nav.highlighted = 0
        await self._show_page("dashboard")

    async def _show_page(
        self,
        page: str,
        *,
        force: bool = False,
        focus_target: str | None = None,
        refresh_models: bool = False,
        refresh_repos: bool = False,
    ) -> None:
        if page not in {item[0] for item in self.NAV}:
            return
        if page != "models":
            self._cancel_model_filter_timer()
        if not force:
            self.selected_provider = (
                None if page != "providers" else self.selected_provider
            )
        self.page = page
        title = dict(self.NAV)[page]
        self.query_one("#page-title", Static).update(title)
        await self._clear_actions()
        table = self.query_one("#table", DataTable)
        model_list = self.query_one("#model-list", VerticalScroll)
        self.query_one("#model-toolbar", Horizontal).display = page == "models"
        model_list.display = page == "models"
        content = self.query_one("#content", VerticalScroll)
        table.clear(columns=True)
        table.display = page not in {
            "dashboard",
            "diagnose",
            "policy",
            "logs",
            "models",
        }
        if page != "models":
            await model_list.remove_children()
        content.display = page in {"dashboard", "diagnose", "policy", "logs"}
        await content.remove_children()

        try:
            if page == "dashboard":
                await self._render_dashboard(content)
            elif page == "providers":
                await self._render_providers(table)
            elif page == "accounts":
                await self._render_accounts(table)
            elif page == "repos":
                await self._render_repos(table, refresh=refresh_repos)
            elif page == "profiles":
                await self._render_profiles(table)
            elif page == "models":
                await self._render_models(table, refresh=refresh_models)
            elif page == "reviewers":
                await self._render_reviewers(table)
            elif page == "usage":
                await self._render_usage(table)
            elif page == "diagnose":
                await self._render_diagnose(content)
            elif page == "policy":
                await self._render_policy(content)
            elif page == "logs":
                await self._render_logs(content)
            elif page == "settings":
                await self._render_settings(table)
        except Exception as exc:
            detail = format_user_error_preview(exc, max_len=240)
            message = f"{title} unavailable: {detail}"
            self.query_one("#summary", Static).update(message)
            self.notify(message, title="Control action failed", severity="error")
        if page == "models":
            if focus_target is not None:
                self.query_one(focus_target).focus()
            else:
                rows = list(model_list.query(ModelToggleButton))
                if rows:
                    target = next(
                        (row for row in rows if row.model_ref == self.selected_model),
                        rows[0],
                    )
                    target.focus()
                else:
                    self.query_one("#model-search", Input).focus()

    async def _render_dashboard(self, content: VerticalScroll) -> None:
        owner = "this terminal" if self.supervisor is not None else "another process"
        status = (
            self.supervisor.status.value
            if self.supervisor is not None
            else ServerStatus.RUNNING.value
        )
        repo = (
            f"{self.selected_repo.identity} · {self.selected_repo.display_path}"
            if self.selected_repo
            else f"(no repository selected) · {Path.cwd()}"
        )
        account_summary = await asyncio.to_thread(fcc_provider_account_summary)
        codex = await asyncio.to_thread(self._safe_codex_summary)
        compatibility_block = False
        text = (
            f"Server       {status} ({owner})\n"
            f"Repository   {repo}\n"
            f"Model        {self.settings.model}\n"
            f"FCC Learning profile  {self.next_profile} (next launch)\n"
            f"OpenAI / ChatGPT  {account_summary}\n"
            f"Codex Tools  {codex}\n"
            f"Context      {context_cap_tokens(os.environ):,} tokens"
        )
        if self.startup_error:
            compatibility_block = "compatibility firewall" in self.startup_error
            summary = (
                "Launch failed safely: FCC blocked the unsafe Claude executable. "
                "Choose Repair & start; "
                "FCC will use an exact known-good fallback or show the repair "
                "command."
                if compatibility_block
                else "Launch failed. Read the error below, then choose Retry "
                "Claude or Retry Danger."
            )
            self.query_one("#summary", Static).update(summary)
            await content.mount(Static(self.startup_error, classes="launch-error-card"))
        else:
            self.query_one("#summary", Static).update(
                "Everything here is selectable; use arrows/mouse + Enter. "
                "No nested prompt menus."
            )
        await content.mount(Static(text, classes="dashboard-card"))
        if self.startup_error:
            claude_label = "Repair & start" if compatibility_block else "Retry Claude"
            danger_label = (
                "Repair & start Danger" if compatibility_block else "Retry Danger"
            )
            await self._add_action("launch-retry-claude", claude_label)
            await self._add_action("launch-retry-danger", danger_label)
        await self._add_action("refresh", "Refresh")

    async def _render_providers(self, table: DataTable) -> None:
        self.query_one("#summary", Static).update(
            "Live connected-account state is overlaid on the config catalog."
        )
        table.add_columns("Provider", "Status", "Type")
        config = await asyncio.to_thread(get_admin_config, self.settings)
        statuses = config.get("provider_status")
        if not isinstance(statuses, list):
            return
        for provider in statuses:
            if not isinstance(provider, dict):
                continue
            provider_id = str(provider.get("provider_id", ""))
            if not provider_id:
                continue
            label = str(provider.get("label", provider.get("status", "unknown")))
            if provider.get("kind") == "connected_account":
                try:
                    live = await asyncio.to_thread(
                        connected_account_status, self.settings, provider_id
                    )
                except LocalAdminError:
                    live = None
                if isinstance(live, dict):
                    state = str(live.get("state", "unknown"))
                    email = live.get("email")
                    label = state.replace("_", " ").title()
                    if isinstance(email, str) and email:
                        label = f"{label} · {email}"
            table.add_row(
                str(provider.get("display_name", provider_id)),
                label,
                str(provider.get("kind", "provider")),
                key=provider_id,
            )
        await self._add_action("provider-open", "Open")
        await self._add_action("provider-test", "Test")
        await self._add_action("refresh", "Refresh")

    async def _render_accounts(self, table: DataTable) -> None:
        account_summary, codex_summary = await asyncio.gather(
            asyncio.to_thread(fcc_provider_account_summary),
            asyncio.to_thread(self._safe_codex_summary),
        )
        self.query_one("#summary", Static).update(
            f"OpenAI / ChatGPT: {account_summary}   |   Codex Tools: {codex_summary}"
        )
        table.add_columns("Codex profile", "Account", "Plan", "Active")
        accounts = await asyncio.to_thread(codex_accounts.list_accounts)
        for account in accounts:
            table.add_row(
                account.profile,
                account.email or "connected",
                account.plan or "unknown",
                "●" if account.active else "",
                key=account.profile,
            )
        await self._add_action("codex-switch", "Switch", disabled=not accounts)
        await self._add_action("codex-refresh", "Refresh usage", disabled=not accounts)
        await self._add_action("fcc-browser", "OpenAI login")
        await self._add_action("fcc-device", "OpenAI device")

    async def _load_repo_inventory(self, *, refresh: bool) -> list[RepoEntry]:
        """Load the repository inventory once, scanning only on demand."""

        if self._repo_inventory_loaded and not refresh:
            return list(self._repo_inventory)

        cache = cache_path()
        repos: list[RepoEntry] = []
        if not refresh and await asyncio.to_thread(cache_is_fresh, cache):
            repos = await asyncio.to_thread(load_cached_repos, cache)
        if not repos:
            repos = await asyncio.to_thread(discover_repos, default_roots())
            repos = deduplicate_repos(repos)
            await asyncio.to_thread(save_cached_repos, repos, cache)

        self._repo_inventory = tuple(deduplicate_repos(repos))
        self._repo_inventory_loaded = True
        return list(self._repo_inventory)

    async def _render_repos(self, table: DataTable, *, refresh: bool = False) -> None:
        repos = await self._load_repo_inventory(refresh=refresh)
        selected_path = self.selected_repo.path if self.selected_repo else None
        selected = next((repo for repo in repos if repo.path == selected_path), None)
        if selected is None and self.selected_repo is not None:
            selected = await asyncio.to_thread(
                repository_from_path,
                Path(self.selected_repo.path),
                last_used=self.selected_repo.last_used,
            )
            if selected is not None:
                repos.append(selected)
                repos = deduplicate_repos(repos)
                self._repo_inventory = tuple(repos)
                await asyncio.to_thread(save_cached_repos, repos, cache_path())
        repos = deduplicate_repos(repos)
        if selected_path is not None:
            selected = next(
                (repo for repo in repos if repo.path == selected_path), None
            )
        self.selected_repo = selected
        self._repos = tuple(repos)
        self.query_one("#summary", Static).update(
            f"Local Git repositories ({len(repos)} found). "
            "GitHub / remote is paired with the local folder; "
            "the marked folder is the default for the next launch. "
            "Use Refresh to rescan."
        )
        # Keep the two fields needed for selection visible in the normal-width
        # pane. Longer path and branch details remain available to the right.
        table.add_column("GitHub / remote", width=26)
        table.add_column("Local folder", width=20)
        table.add_column("Branch", width=16)
        table.add_column("Path", width=32)
        for repo in repos:
            local_folder = f"● {repo.name}" if repo.path == selected_path else repo.name
            table.add_row(
                repo.identity,
                local_folder,
                repo.branch,
                repo.display_path,
                key=repo.path,
            )
        if selected_path is not None:
            selected_index = next(
                (
                    index
                    for index, repo in enumerate(repos)
                    if repo.path == selected_path
                ),
                None,
            )
            if selected_index is not None:
                table.move_cursor(row=selected_index, column=0)
        await self._add_action("repo-select", "Use selected", disabled=not repos)
        await self._add_action("repo-open", "Open path")
        await self._add_action("repo-refresh", "Refresh")

    async def _render_profiles(self, table: DataTable) -> None:
        profiles, active = await asyncio.gather(
            asyncio.to_thread(list_profiles),
            asyncio.to_thread(configured_profile),
        )
        self.query_one("#summary", Static).update(
            "FCC Learning profile — "
            f"running: {active}   |   next launch: {self.next_profile}"
        )
        table.add_columns("FCC Learning profile", "Running", "Next launch")
        for profile in profiles:
            table.add_row(
                profile,
                "●" if profile == active else "",
                "●" if profile == self.next_profile else "",
                key=profile,
            )
        await self._add_action("profile-create", "Create")
        await self._add_action("profile-select", "Use next", disabled=not profiles)

    @on(Button.Pressed, "#profile-create")
    def profile_create(self) -> None:
        """Open the non-blocking profile creation prompt."""

        def callback(value: str | None) -> None:
            if value is not None:
                self.run_worker(self._create_profile(value))

        self.push_screen(
            InputModal(
                "Create profile",
                "Name (lowercase letters, digits, '.', '_' or '-')",
            ),
            callback,
        )

    async def _create_profile(self, requested_name: str) -> None:
        try:
            name = await asyncio.to_thread(create_profile, requested_name)
        except LearningProfileError as exc:
            self.notify(str(exc), title="Profile creation failed", severity="error")
            return
        self.next_profile = name
        self.notify(f"Created and selected profile: {name}")
        await self._show_page("profiles", force=True)

    async def _load_model_catalog(self, *, refresh: bool = False) -> dict[str, Any]:
        """Load model discovery once per app, unless the user explicitly refreshes."""

        if not refresh and self._model_catalog_result is not None:
            return self._model_catalog_result
        if self._model_catalog_lock is None:
            self._model_catalog_lock = asyncio.Lock()
        async with self._model_catalog_lock:
            if not refresh and self._model_catalog_result is not None:
                return self._model_catalog_result
            result = await asyncio.to_thread(
                get_models,
                self.settings,
                refresh=refresh,
            )
            self._model_catalog_result = result
            return result

    async def _render_models(self, table: DataTable, *, refresh: bool = False) -> None:
        del table
        result = await self._load_model_catalog(refresh=refresh)
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
        labels = result.get("catalog_model_labels", result.get("model_labels"))
        evidence = result.get("catalog_model_evidence", result.get("model_evidence"))
        enabled_models = _model_catalog_enabled_models(self.settings, model_refs)
        effective_models = _model_catalog_effective_models(
            self.settings,
            model_refs,
            legacy_visible_models=visible_refs,
        )
        configured_models = set(_configured_model_refs(self.settings))
        self.selected_models.intersection_update(model_refs)

        model_list = self.query_one("#model-list", VerticalScroll)
        highlighted_model = self._highlighted_model_ref(model_list)
        if highlighted_model is None:
            highlighted_model = self.selected_model

        providers = sorted(
            {_model_provider_id(model) for model in model_refs},
            key=str.casefold,
        )
        provider_options = tuple(
            [("All providers", "all")]
            + [
                (
                    (
                        PROVIDER_CATALOG[provider].display_name
                        if provider in PROVIDER_CATALOG
                        else provider
                    ),
                    provider,
                )
                for provider in providers
            ]
        )
        provider_select = self.query_one("#model-provider", Select)
        if self.model_provider_filter not in {"all", *providers}:
            self.model_provider_filter = "all"
        if provider_options != self._model_provider_options:
            self._updating_model_controls = True
            try:
                provider_select.set_options(provider_options)
            finally:
                self._updating_model_controls = False
            self._model_provider_options = provider_options
        if provider_select.value != self.model_provider_filter:
            self._updating_model_controls = True
            try:
                provider_select.value = self.model_provider_filter
            finally:
                self._updating_model_controls = False

        price_select = self.query_one("#model-price", Select)
        if self.model_price_filter not in {"all", "free-first", "free-only"}:
            self.model_price_filter = "free-first"
        if price_select.value != self.model_price_filter:
            self._updating_model_controls = True
            try:
                price_select.value = self.model_price_filter
            finally:
                self._updating_model_controls = False

        filtered_refs = [
            model
            for model in sorted(
                model_refs,
                key=lambda value: _model_sort_key(value, labels, evidence),
            )
            if self._model_matches_filter(model, labels, evidence)
        ]
        mode = _model_catalog_mode(self.settings)
        catalog_summary = mode.value if mode is not None else "legacy"
        price_summary = {
            "all": "all prices",
            "free-first": "free first",
            "free-only": "free only",
        }[self.model_price_filter]
        free_count = sum(
            _model_price_state(model, evidence) == "free" for model in model_refs
        )
        summary = (
            f"Current: {self.settings.model}   |   Policy: {catalog_summary}   |   "
            f"Price: {price_summary}   |   Free: {free_count}   |   "
            f"Explicit: {len(enabled_models)}   |   Pending: {len(self.selected_models)}   |   "
            f"Showing: {len(filtered_refs)}/{len(model_refs)}\n"
            "Select rows with Space or a click. ON is effective access; the toggle "
            "is the pending bulk-action selection."
        )
        if not model_refs:
            summary += "\nNo cached discoveries yet. Press Refresh to query configured providers."
        self._model_summary_text = summary
        self.query_one("#summary", Static).update(summary)

        await model_list.remove_children()
        for model in filtered_refs:
            friendly = model
            if isinstance(labels, dict) and isinstance(labels.get(model), str):
                friendly = str(labels[model])
            source = "unknown"
            if isinstance(evidence, dict) and isinstance(evidence.get(model), dict):
                source = str(evidence[model].get("evidence_source", "unknown"))
            access = "ON" if model in effective_models else "OFF"
            configured = " · configured" if model in configured_models else ""
            price = _model_price_label(model, evidence)
            label = (
                f"{access}{configured}  {price}  {friendly}  |  {model}  |  {source}"
            )
            await model_list.mount(
                ModelToggleButton(
                    model,
                    label,
                    pending=model in self.selected_models,
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

        if filtered_refs:
            target = (
                highlighted_model
                if highlighted_model in filtered_refs
                else filtered_refs[0]
            )
            self.selected_model = target
        else:
            self.selected_model = None

        await self._add_action("model-select", "Use model", disabled=not filtered_refs)
        await self._add_action(
            "models-enable", "Enable selected", disabled=not self.selected_models
        )
        await self._add_action(
            "models-disable", "Disable selected", disabled=not self.selected_models
        )
        await self._add_action("models-disable-all", "Disable all")
        await self._add_action("refresh", "Refresh")

    def _highlighted_model_ref(self, model_list: VerticalScroll) -> str | None:
        """Return the model under the model-list focus, if any."""

        focused = self.focused
        if isinstance(focused, ModelToggleButton) and focused.parent is model_list:
            return focused.model_ref
        return None

    def _model_list_index(self, model_list: VerticalScroll, model: str) -> int:
        """Find a model row by its value for focused navigation and tests."""

        for index, row in enumerate(model_list.query(ModelToggleButton)):
            if row.model_ref == model:
                return index
        return 0

    def _model_matches_filter(
        self, model: str, labels: Any, evidence: Any = None
    ) -> bool:
        if (
            self.model_provider_filter != "all"
            and _model_provider_id(model) != self.model_provider_filter
        ):
            return False
        if (
            self.model_price_filter == "free-only"
            and _model_price_state(model, evidence) != "free"
        ):
            return False
        search = self.model_search.casefold()
        if not search:
            return True
        friendly = labels.get(model) if isinstance(labels, dict) else None
        return search in model.casefold() or (
            isinstance(friendly, str) and search in friendly.casefold()
        )

    async def _render_reviewers(self, table: DataTable) -> None:
        status = await asyncio.to_thread(reviewer_status, profile=self.next_profile)
        self.query_one("#summary", Static).update(
            f"Reviewer/scar state for profile {self.next_profile}."
        )
        table.add_columns("Pack", "Mode", "State")
        packs = status.get("packs")
        if isinstance(packs, list):
            for pack in packs:
                if isinstance(pack, Mapping):
                    name = str(pack.get("pack", "?"))
                    table.add_row(
                        name,
                        str(pack.get("mode", "automatic")),
                        "enabled" if pack.get("enabled", True) else "disabled",
                        key=f"pack:{name}",
                    )
        scars = status.get("scars")
        if isinstance(scars, list):
            for scar in scars[:100]:
                if isinstance(scar, Mapping):
                    scar_id = str(scar.get("scar_id", "?"))
                    table.add_row(
                        f"scar {scar_id}",
                        str(scar.get("kind", "?")),
                        str(scar.get("state", "?")),
                        key=f"scar:{scar_id}",
                    )
        await self._add_action("refresh", "Refresh")

    async def _render_usage(self, table: DataTable) -> None:
        result = await asyncio.to_thread(get_usage, self.settings, days=30)
        self.query_one("#summary", Static).update("Local metadata-only usage · 30 days")
        table.add_columns("Metric", "Value")
        totals = result.get("totals")
        if isinstance(totals, Mapping):
            for key, value in totals.items():
                table.add_row(str(key), str(value))
        await self._add_action("refresh", "Refresh")

    async def _render_diagnose(self, content: VerticalScroll) -> None:
        result = await asyncio.to_thread(
            route_diagnostic,
            self.settings,
            model=self.settings.model,
            shapes=("text",),
            mode="strict",
        )
        self.query_one("#summary", Static).update("Current strict text route")
        await content.mount(Static(json.dumps(result, indent=2, sort_keys=True)))
        await self._add_action("refresh", "Refresh")

    async def _render_policy(self, content: VerticalScroll) -> None:
        status = await asyncio.to_thread(get_admin_status, self.settings)
        policy = status.get("session_policy", {})
        self.query_one("#summary", Static).update("Live session policy receipt")
        await content.mount(Static(json.dumps(policy, indent=2, sort_keys=True)))
        await self._add_action("refresh", "Refresh")

    async def _render_logs(self, content: VerticalScroll) -> None:
        path = server_log_path()
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[
                -200:
            ]
        except OSError as exc:
            lines = [f"Log unavailable ({type(exc).__name__})"]
        self.query_one("#summary", Static).update(str(path))
        await content.mount(Static("\n".join(lines)))
        await self._add_action("refresh", "Refresh")

    async def _render_settings(self, table: DataTable) -> None:
        config = await asyncio.to_thread(get_admin_config, self.settings)
        self.query_one("#summary", Static).update(
            "Select a field and press Edit. Secrets are never rendered."
        )
        table.add_columns("Setting", "Value", "Source", "Locked")
        fields = config.get("fields")
        if isinstance(fields, list):
            for field in fields:
                if not isinstance(field, dict):
                    continue
                key = str(field.get("key", ""))
                if not key:
                    continue
                if field.get("secret"):
                    value = "configured" if field.get("configured") else "missing"
                else:
                    value = str(field.get("value", ""))
                table.add_row(
                    str(field.get("label", key)),
                    value,
                    str(field.get("source", "")),
                    "yes" if field.get("locked") else "",
                    key=key,
                )
        await self._add_action("setting-edit", "Edit", disabled=not table.row_count)
        await self._add_action("refresh", "Refresh")

    async def _clear_actions(self) -> None:
        actions = self.query_one("#actions", Horizontal)
        await actions.remove_children()

    async def _add_action(
        self, action_id: str, label: str, *, disabled: bool = False
    ) -> None:
        await self.query_one("#actions", Horizontal).mount(
            Button(label, id=action_id, disabled=disabled)
        )

    def _cancel_model_filter_timer(self) -> None:
        """Cancel a pending search render before leaving or refreshing the page."""

        timer = self._model_filter_timer
        if timer is not None:
            timer.stop()
            self._model_filter_timer = None

    def _schedule_model_filter_render(self, focus_target: str) -> None:
        """Debounce model filtering so typing does not rebuild hundreds of rows."""

        self._cancel_model_filter_timer()
        self._model_filter_timer = self.set_timer(
            self.MODEL_FILTER_DEBOUNCE_SECONDS,
            lambda: self._render_model_filter_page(focus_target),
        )

    async def _render_model_filter_page(self, focus_target: str) -> None:
        self._model_filter_timer = None
        if self.page == "models":
            await self._show_page(
                "models",
                force=True,
                focus_target=focus_target,
            )

    @on(Button.Pressed, "#refresh")
    async def refresh_button(self) -> None:
        await self.action_refresh()

    @on(DataTable.RowSelected, "#table")
    async def row_selected(self, event: DataTable.RowSelected) -> None:
        value = str(event.row_key.value)
        if self.page == "providers":
            self.selected_provider = value
            await self._show_provider_detail(value)
        elif self.page == "accounts":
            self.selected_codex_profile = value
        elif self.page == "repos":
            repo = self._repo_for_path(value)
            if repo is not None:
                self.selected_repo = repo
                self.notify(
                    f"Next launch repository: {repo.identity} · {repo.display_path}"
                )
                await self._show_page("repos", force=True)
        elif self.page == "profiles":
            self.next_profile = value
            self.notify(f"Next launch profile: {value}")
            await self._show_page("profiles", force=True)

    @on(Button.Pressed, "#model-list ModelToggleButton")
    def model_toggled(self, event: Button.Pressed) -> None:
        if not isinstance(event.button, ModelToggleButton):
            return
        model = event.button.model_ref
        if model in self.selected_models:
            self.selected_models.remove(model)
        else:
            self.selected_models.add(model)
        event.button.set_pending(model in self.selected_models)
        self._update_model_summary()

    @on(Input.Changed, "#model-search")
    def model_search_changed(self, event: Input.Changed) -> None:
        if self._updating_model_controls:
            return
        self.model_search = event.value.strip()
        if self.page == "models":
            self._schedule_model_filter_render("#model-search")

    @on(Select.Changed, "#model-provider")
    async def model_provider_changed(self, event: Select.Changed) -> None:
        if self._updating_model_controls:
            return
        value = event.value
        if value is Select.NULL:
            return
        next_filter = value if isinstance(value, str) else "all"
        if next_filter == self.model_provider_filter:
            return
        self.model_provider_filter = next_filter
        if self.page == "models":
            self._cancel_model_filter_timer()
            await self._show_page(
                "models",
                force=True,
                focus_target="#model-provider",
            )

    @on(Select.Changed, "#model-price")
    async def model_price_changed(self, event: Select.Changed) -> None:
        if self._updating_model_controls:
            return
        value = event.value
        if value is Select.NULL:
            return
        next_filter = value if isinstance(value, str) else "free-first"
        if next_filter not in {"all", "free-first", "free-only"}:
            next_filter = "free-first"
        if next_filter == self.model_price_filter:
            return
        self.model_price_filter = next_filter
        if self.page == "models":
            self._cancel_model_filter_timer()
            await self._show_page(
                "models",
                force=True,
                focus_target="#model-price",
            )

    def _update_model_summary(self) -> None:
        """Update the pending count without rebuilding the model list."""

        text = self._model_summary_text
        marker = " | Pending: "
        if marker not in text:
            return
        prefix, remainder = text.split(marker, 1)
        _old_count, suffix = remainder.split(" | ", 1)
        self._model_summary_text = (
            f"{prefix}{marker}{len(self.selected_models)} | {suffix}"
        )
        self.query_one("#summary", Static).update(self._model_summary_text)
        model_list = self.query_one("#model-list", VerticalScroll)
        for row in model_list.query(ModelToggleButton):
            row.set_pending(row.model_ref in self.selected_models)

    @on(Button.Pressed, "#provider-open")
    async def open_provider_button(self) -> None:
        table = self.query_one("#table", DataTable)
        if table.cursor_row >= 0 and table.row_count:
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            await self._show_provider_detail(str(key.value))
        else:
            self._notify_missing_selection("provider")

    async def _show_provider_detail(self, provider_id: str) -> None:
        """Render provider detail or keep the failure visible in the TUI."""

        self.selected_provider = provider_id
        try:
            await self._render_provider_detail(provider_id)
        except Exception as exc:
            table = self.query_one("#table", DataTable)
            table.clear(columns=True)
            table.add_columns("Field", "Value")
            message = "Provider details unavailable: " + format_user_error_preview(
                exc, max_len=240
            )
            self.query_one("#page-title", Static).update(provider_id)
            self.query_one("#summary", Static).update(message)
            await self._clear_actions()
            await self._add_action("provider-back", "Back")
            self.notify(message, title="Provider action failed", severity="error")

    async def _render_provider_detail(self, provider_id: str) -> None:
        self.selected_provider = provider_id
        table = self.query_one("#table", DataTable)
        table.clear(columns=True)
        table.add_columns("Field", "Value")
        descriptor = PROVIDER_CATALOG.get(provider_id)
        config = await asyncio.to_thread(get_admin_config, self.settings)
        provider = self._provider_from_config(config, provider_id)
        name = (
            str(provider.get("display_name", provider_id)) if provider else provider_id
        )
        self.query_one("#page-title", Static).update(name)
        await self._clear_actions()

        if (
            descriptor is not None
            and descriptor.auth_kind is ProviderAuthKind.CONNECTED_ACCOUNT
        ):
            status = await asyncio.to_thread(
                connected_account_status, self.settings, provider_id
            )
            for key in ("state", "email", "model_count", "message"):
                value = status.get(key)
                if value not in (None, ""):
                    table.add_row(key.replace("_", " ").title(), str(value))
            await self._add_action("fcc-browser", "Browser login")
            await self._add_action("fcc-device", "Device login")
            state = str(status.get("state", ""))
            if state in {"connecting", "pending"}:
                await self._add_action("fcc-cancel", "Cancel login")
            if status.get("connected"):
                await self._add_action("fcc-disconnect", "Disconnect")
            await self._add_action("provider-test", "Test")
            await self._add_action("provider-back", "Back")
            return

        fields = self._provider_fields(config, provider_id)
        for key, field in fields:
            value = (
                "configured"
                if field.get("secret") and field.get("configured")
                else "missing"
                if field.get("secret")
                else str(field.get("value", ""))
            )
            table.add_row(str(field.get("label", key)), value, key=key)
        await self._add_action("provider-field-edit", "Edit", disabled=not fields)
        await self._add_action("provider-test", "Test")
        await self._add_action("provider-back", "Back")

    @on(Button.Pressed, "#provider-back")
    async def provider_back(self) -> None:
        self.selected_provider = None
        await self._show_page("providers", force=True)

    @on(Button.Pressed, "#provider-test")
    async def provider_test_button(self) -> None:
        provider_id = self.selected_provider
        if provider_id is None:
            table = self.query_one("#table", DataTable)
            if not table.row_count:
                self._notify_missing_selection("provider")
                return
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            provider_id = str(key.value)
        try:
            result = await asyncio.to_thread(test_provider, self.settings, provider_id)
        except LocalAdminError as exc:
            self.notify(str(exc), severity="error")
        except Exception as exc:
            self._notify_action_error("Provider test failed", exc)
        else:
            count = result.get("model_count", result.get("count", "ok"))
            self.notify(f"{provider_id}: {count}", title="Provider test")

    @on(Button.Pressed, "#fcc-browser")
    async def fcc_browser_login(self) -> None:
        await self._start_fcc_login(ConnectedAccountLoginMode.BROWSER)

    @on(Button.Pressed, "#fcc-device")
    async def fcc_device_login(self) -> None:
        await self._start_fcc_login(ConnectedAccountLoginMode.DEVICE)

    async def _start_fcc_login(self, mode: ConnectedAccountLoginMode) -> None:
        provider_id = self.selected_provider or "openai"
        try:
            status = await asyncio.to_thread(
                start_connected_account_login,
                self.settings,
                provider_id,
                mode,
            )
        except LocalAdminError as exc:
            self.notify(str(exc), title="Login failed", severity="error")
            return
        except Exception as exc:
            self._notify_action_error("Login failed", exc)
            return
        self._oauth_provider = provider_id
        self._oauth_last_state = str(status.get("state", "connecting"))
        self._oauth_poll_error_notified = False
        url = status.get("authorization_url") or status.get("verification_url")
        if isinstance(url, str) and url:
            try:
                opened = webbrowser.open(url)
            except OSError as exc:
                self.notify(
                    f"Could not open the browser: {type(exc).__name__}",
                    title="FCC login",
                    severity="error",
                )
            else:
                if not opened:
                    self.notify(
                        "The browser did not open; use the displayed login URL or device code.",
                        title="FCC login",
                        severity="warning",
                    )
        elif mode is ConnectedAccountLoginMode.BROWSER:
            self.notify(
                "FCC did not return a browser URL.",
                title="FCC login",
                severity="error",
            )
        code = status.get("user_code")
        if isinstance(code, str) and code:
            self.notify(f"Device code: {code}", title="OpenAI device login", timeout=15)
        else:
            self.notify(
                "Browser opened. Waiting for OpenAI to finish…", title="FCC login"
            )
        await self._show_provider_detail(provider_id)

    @on(Button.Pressed, "#fcc-disconnect")
    async def fcc_disconnect(self) -> None:
        provider_id = self.selected_provider or "openai"

        def callback(confirmed: bool | None) -> None:
            if confirmed:
                self.run_worker(self._disconnect_fcc(provider_id))

        self.push_screen(
            ConfirmModal("Disconnect the OpenAI / ChatGPT account from FCC?"),
            callback,
        )

    async def _disconnect_fcc(self, provider_id: str) -> None:
        try:
            await asyncio.to_thread(
                disconnect_connected_account, self.settings, provider_id
            )
        except LocalAdminError as exc:
            self.notify(str(exc), severity="error")
        except Exception as exc:
            self._notify_action_error("Disconnect failed", exc)
        else:
            self.notify("OpenAI / ChatGPT account disconnected from FCC.")
            await self._show_provider_detail(provider_id)

    @on(Button.Pressed, "#fcc-cancel")
    async def fcc_cancel_login(self) -> None:
        provider_id = self.selected_provider or "openai"
        try:
            await asyncio.to_thread(
                cancel_connected_account_login, self.settings, provider_id
            )
        except LocalAdminError as exc:
            self.notify(str(exc), title="Login cancellation failed", severity="error")
            return
        except Exception as exc:
            self._notify_action_error("Login cancellation failed", exc)
            return
        self._oauth_provider = None
        self._oauth_last_state = None
        self._oauth_poll_error_notified = False
        self.notify("OpenAI / ChatGPT login cancelled.")
        await self._show_provider_detail(provider_id)

    @on(Button.Pressed, "#provider-field-edit")
    async def provider_field_edit(self) -> None:
        provider_id = self.selected_provider
        if provider_id is None:
            self._notify_missing_selection("provider")
            return
        table = self.query_one("#table", DataTable)
        if not table.row_count:
            self._notify_missing_selection("provider field")
            return
        key = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        try:
            config = await asyncio.to_thread(get_admin_config, self.settings)
        except Exception as exc:
            self._notify_action_error("Provider field lookup failed", exc)
            return
        field = next(
            (
                item
                for item in config.get("fields", [])
                if isinstance(item, dict) and item.get("key") == key
            ),
            None,
        )
        if not isinstance(field, dict):
            self.notify("Select an editable provider field first.", severity="warning")
            return
        if field.get("locked"):
            self.notify(f"{key} is locked by {field.get('source', 'external config')}.")
            return

        def callback(value: str | None) -> None:
            if value is not None:
                self.run_worker(self._apply_field(provider_id, key, value))

        self.push_screen(
            InputModal(
                str(field.get("label", key)),
                "Enter new value",
                secret=bool(field.get("secret")),
            ),
            callback,
        )

    async def _apply_field(self, provider_id: str, key: str, value: str) -> None:
        try:
            result = await asyncio.to_thread(
                apply_admin_values, self.settings, {key: value}
            )
        except LocalAdminError as exc:
            self.notify(str(exc), severity="error")
            return
        except Exception as exc:
            self._notify_action_error("Provider field update failed", exc)
            return
        if result.get("applied") is True:
            get_settings.cache_clear()
            self.notify(f"Applied {key}.")
            await self._show_provider_detail(provider_id)
        else:
            self.notify(f"{key} was rejected.", severity="error")

    @on(Button.Pressed, "#codex-switch")
    async def codex_switch(self) -> None:
        profile = self.selected_codex_profile or self._selected_table_key()
        if not profile:
            self._notify_missing_selection("Codex account")
            return
        try:
            account = await asyncio.to_thread(codex_accounts.select_account, profile)
        except codex_accounts.CodexAccountError as exc:
            self.notify(str(exc), severity="error")
        except Exception as exc:
            self._notify_action_error("Codex account switch failed", exc)
        else:
            self.notify(f"Codex Tools → {account.email or account.profile}")
            await self._show_page("accounts", force=True)

    @on(Button.Pressed, "#codex-refresh")
    async def codex_refresh(self) -> None:
        profile = self.selected_codex_profile or self._selected_table_key()
        if not profile:
            self._notify_missing_selection("Codex account")
            return
        try:
            await asyncio.to_thread(codex_accounts.refresh_usage, profile)
        except codex_accounts.CodexAccountError as exc:
            self.notify(str(exc), severity="error")
        except Exception as exc:
            self._notify_action_error("Codex usage refresh failed", exc)
        else:
            self.notify(f"Refreshed {profile} usage.")
            await self._show_page("accounts", force=True)

    @on(Button.Pressed, "#repo-select")
    async def repo_select(self) -> None:
        path = self._selected_table_key()
        repo = self._repo_for_path(path) if path else None
        if repo is None:
            self._notify_missing_selection("repository")
            return
        self.selected_repo = repo
        self.notify(f"Next launch repository: {repo.identity} · {repo.display_path}")
        await self._show_page("repos", force=True)

    @on(Button.Pressed, "#repo-open")
    def repo_open(self) -> None:
        """Open and select a repository outside the standard scan roots."""

        def callback(value: str | None) -> None:
            if value is not None:
                self.run_worker(self._open_repo_path(value))

        self.push_screen(
            InputModal(
                "Open local repository",
                "Path to a Git repository (a subdirectory is okay)",
            ),
            callback,
        )

    async def _open_repo_path(self, value: str) -> None:
        repo = await asyncio.to_thread(repository_from_path, Path(value))
        if repo is None:
            self.notify(
                "That path is not inside a readable local Git repository.",
                title="Repository not found",
                severity="error",
            )
            return
        self.selected_repo = deduplicate_repos([repo])[0]
        self.notify(f"Default repository → {self.selected_repo.identity}")
        await self._show_page("repos", force=True)

    @on(Button.Pressed, "#repo-refresh")
    async def repo_refresh(self) -> None:
        self.notify("Scanning local repository roots…")
        await self._show_page("repos", force=True, refresh_repos=True)

    @on(Button.Pressed, "#profile-select")
    async def profile_select(self) -> None:
        profile = self._selected_table_key()
        if not profile:
            self._notify_missing_selection("profile")
            return
        self.next_profile = profile
        self.notify(f"Next launch profile: {profile}")
        await self._show_page("profiles", force=True)

    @on(Button.Pressed, "#model-select")
    async def model_select(self) -> None:
        model = self._selected_table_key()
        if not model:
            self._notify_missing_selection("model")
            return
        try:
            result = await asyncio.to_thread(
                apply_admin_values,
                self.settings,
                {"MODEL": model},
            )
        except LocalAdminError as exc:
            self.notify(str(exc), severity="error")
            return
        except Exception as exc:
            self._notify_action_error("Model selection failed", exc)
            return
        if result.get("applied") is True:
            get_settings.cache_clear()
            self.settings.model = model
            self.selected_model = model
            self.notify(f"Model → {model}")
            await self._show_page("models", force=True)
        else:
            self.notify("Model update was rejected.", severity="error")

    @on(Button.Pressed, "#models-enable")
    async def enable_selected_models(self) -> None:
        """Add the pending model refs to the explicit curated allowlist."""

        if not self.selected_models:
            self.notify("Select models first with Space.", severity="warning")
            return
        existing = _model_catalog_allowlist(self.settings)
        enabled = set(existing)
        enabled.update(self.selected_models)
        await self._apply_model_catalog(
            mode="curated",
            allowlist=", ".join(sorted(enabled, key=str.casefold)),
            message=f"Enabled {len(self.selected_models)} selected model(s).",
        )

    @on(Button.Pressed, "#models-disable")
    async def disable_selected_models(self) -> None:
        """Remove the pending model refs from the explicit curated allowlist."""

        if not self.selected_models:
            self.notify("Select models first with Space.", severity="warning")
            return
        allowlist = set(_model_catalog_allowlist(self.settings))
        mode = _model_catalog_mode(self.settings)
        if (
            mode is ModelCatalogMode.ALL
            or mode is None
            or any(entry == "*" or entry.endswith("/*") for entry in allowlist)
        ):
            result = await self._load_model_catalog()
            raw_models = result.get("catalog_models", result.get("models"))
            model_refs = (
                {str(raw) for raw in raw_models if raw is not None}
                if isinstance(raw_models, list)
                else set()
            )
            visible_models = result.get("models")
            visible_refs = (
                {str(raw) for raw in visible_models if raw is not None}
                if isinstance(visible_models, list)
                else set()
            )
            enabled = _model_catalog_effective_models(
                self.settings,
                model_refs,
                legacy_visible_models=visible_refs,
            )
            enabled.difference_update(self.selected_models)
            enabled.update(
                entry
                for entry in allowlist
                if "/" in entry
                and not entry.endswith("/*")
                and entry != "*"
                and entry not in self.selected_models
            )
        else:
            enabled = allowlist.difference(self.selected_models)
        count = len(self.selected_models)
        await self._apply_model_catalog(
            mode="curated",
            allowlist=", ".join(sorted(enabled, key=str.casefold)),
            message=f"Disabled {count} selected model(s).",
        )

    @on(Button.Pressed, "#models-disable-all")
    async def disable_all_models(self) -> None:
        """Disable every discovered model while retaining configured routes."""

        await self._apply_model_catalog(
            mode="curated",
            allowlist="",
            message="All discovered models disabled.",
        )

    async def _apply_model_catalog(
        self, *, mode: str, allowlist: str, message: str
    ) -> None:
        try:
            result = await asyncio.to_thread(
                apply_admin_values,
                self.settings,
                {
                    "MODEL_CATALOG_MODE": mode,
                    "MODEL_CATALOG_ALLOWLIST": allowlist,
                },
            )
        except LocalAdminError as exc:
            self.notify(str(exc), severity="error")
            return
        except Exception as exc:
            self._notify_action_error("Model catalog update failed", exc)
            return
        if result.get("applied") is True:
            get_settings.cache_clear()
            self.settings.model_catalog_mode = ModelCatalogMode(mode)
            self.settings.model_catalog_allowlist = allowlist
            self.selected_models.clear()
            self.notify(message)
            await self._show_page("models", force=True)
        else:
            self.notify("Model catalog update was rejected.", severity="error")

    @on(Button.Pressed, "#setting-edit")
    async def setting_edit(self) -> None:
        key = self._selected_table_key()
        if not key:
            self._notify_missing_selection("setting")
            return
        try:
            config = await asyncio.to_thread(get_admin_config, self.settings)
        except Exception as exc:
            self._notify_action_error("Settings lookup failed", exc)
            return
        field = next(
            (
                item
                for item in config.get("fields", [])
                if isinstance(item, dict) and item.get("key") == key
            ),
            None,
        )
        if not isinstance(field, dict):
            self.notify("Select an editable setting first.", severity="warning")
            return
        if field.get("locked"):
            self.notify(f"{key} is locked by {field.get('source', 'external config')}.")
            return

        def callback(value: str | None) -> None:
            if value is not None:
                self.run_worker(self._apply_setting(key, value))

        self.push_screen(
            InputModal(
                str(field.get("label", key)),
                "Enter new value",
                secret=bool(field.get("secret")),
            ),
            callback,
        )

    async def _apply_setting(self, key: str, value: str) -> None:
        try:
            result = await asyncio.to_thread(
                apply_admin_values, self.settings, {key: value}
            )
        except LocalAdminError as exc:
            self.notify(str(exc), severity="error")
            return
        except Exception as exc:
            self._notify_action_error("Setting update failed", exc)
            return
        if result.get("applied") is True:
            get_settings.cache_clear()
            self.notify(f"Applied {key}.")
            await self._show_page("settings", force=True)
        else:
            self.notify(f"{key} was rejected.", severity="error")

    async def _poll_live_state(self) -> None:
        provider_id = self._oauth_provider
        if provider_id is None:
            return
        if self._oauth_poll_in_flight:
            return
        self._oauth_poll_in_flight = True
        try:
            try:
                status = await asyncio.to_thread(
                    connected_account_status, self.settings, provider_id
                )
            except LocalAdminError:
                return
            except Exception as exc:
                if not self._oauth_poll_error_notified:
                    self._notify_action_error("Login status check failed", exc)
                    self._oauth_poll_error_notified = True
                return
        finally:
            self._oauth_poll_in_flight = False
        self._oauth_poll_error_notified = False
        state = str(status.get("state", "unknown"))
        if state != self._oauth_last_state:
            self._oauth_last_state = state
            if state == "connected":
                email = status.get("email")
                suffix = f" · {email}" if isinstance(email, str) and email else ""
                self.notify(
                    f"OpenAI / ChatGPT account connected{suffix}",
                    title="Login complete",
                )
                self._oauth_provider = None
            elif state == "error":
                self.notify(
                    str(status.get("message", "OpenAI login failed.")),
                    title="Login failed",
                    severity="error",
                )
                self._oauth_provider = None
        if self.page == "providers" and self.selected_provider == provider_id:
            await self._show_provider_detail(provider_id)
        elif self.page in {"providers", "accounts", "dashboard"}:
            await self._show_page(self.page, force=True)

    def _selected_table_key(self) -> str | None:
        if self.page == "models":
            highlighted = self._highlighted_model_ref(
                self.query_one("#model-list", VerticalScroll)
            )
            if highlighted is not None:
                return highlighted
            selected = self.selected_model
            if selected is not None and any(
                row.model_ref == selected
                for row in self.query_one("#model-list", VerticalScroll).query(
                    ModelToggleButton
                )
            ):
                return selected
            return None
        table = self.query_one("#table", DataTable)
        if not table.row_count or table.cursor_row < 0:
            return None
        return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)

    def _repo_for_path(self, path: str) -> RepoEntry | None:
        return next((repo for repo in self._repos if repo.path == path), None)

    def _notify_missing_selection(self, label: str) -> None:
        """Explain an unavailable row action instead of silently doing nothing."""

        self.notify(f"Select a {label} first.", severity="warning")

    def _notify_action_error(self, title: str, exc: BaseException) -> None:
        """Show a short, redacted failure instead of letting an action vanish."""

        self.notify(
            format_user_error_preview(exc, max_len=240),
            title=title,
            severity="error",
        )

    def _provider_from_config(
        self, config: Mapping[str, Any], provider_id: str
    ) -> Mapping[str, Any] | None:
        statuses = config.get("provider_status")
        if not isinstance(statuses, list):
            return None
        return next(
            (
                item
                for item in statuses
                if isinstance(item, Mapping) and item.get("provider_id") == provider_id
            ),
            None,
        )

    def _provider_fields(
        self, config: Mapping[str, Any], provider_id: str
    ) -> tuple[tuple[str, Mapping[str, Any]], ...]:
        descriptor = PROVIDER_CATALOG.get(provider_id)
        if descriptor is None:
            return ()
        fields = config.get("fields")
        if not isinstance(fields, list):
            return ()
        by_key = {
            str(item.get("key")): item
            for item in fields
            if isinstance(item, Mapping) and item.get("key")
        }
        settings_attrs = list(descriptor.configuration_attrs())
        for attr in (descriptor.base_url_attr, descriptor.proxy_attr):
            if attr is not None and attr not in settings_attrs:
                settings_attrs.append(attr)
        resolved: list[tuple[str, Mapping[str, Any]]] = []
        for attr in settings_attrs:
            model_field = Settings.model_fields.get(attr)
            if model_field is None:
                continue
            if attr == descriptor.credential_attr and descriptor.credential_env:
                key = descriptor.credential_env
            elif model_field.validation_alias is not None:
                key = str(model_field.validation_alias)
            elif model_field.alias is not None:
                key = str(model_field.alias)
            else:
                key = attr.upper()
            field = by_key.get(key)
            if field is not None:
                resolved.append((key, field))
        return tuple(resolved)

    def _safe_codex_summary(self) -> str:
        try:
            return codex_accounts.active_account_summary()
        except Exception:
            return "needs attention"


def run_control_tui(
    settings: Settings,
    *,
    supervisor: ServerSupervisor | None,
    launch_client: Callable[[bool, Sequence[str], Path | None], None],
    startup_error: str | None = None,
) -> None:
    """Run the Harlequin-derived control shell and temporarily yield to Claude."""

    selected_repo: RepoEntry | None = None
    server_profile = configured_profile()
    next_profile = server_profile
    while True:
        result = ControlCenterApp(
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
