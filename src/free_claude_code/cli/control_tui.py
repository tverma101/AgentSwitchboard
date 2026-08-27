"""Textual control center backed by CodeSwitchyard's existing admin/actions.

UI shell/layout/focus/modal patterns are adapted from Harlequin at
fcfaa6c524a6cd47e17701d931eac0243c8c85b6 (MIT, Ted Conbeer).
See THIRD_PARTY_NOTICES.md. The CodeSwitchyard-specific code in this module is
limited to feeding existing local actions/state into that shell.
"""

import asyncio
import json
import os
import time
import webbrowser
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    Static,
)
from textual.widgets.option_list import Option

from free_claude_code.application.account_identity import fcc_provider_account_summary
from free_claude_code.application.connected_accounts import ConnectedAccountLoginMode
from free_claude_code.cli.claude_env import context_cap_tokens
from free_claude_code.cli.commands import ServerStatus, ServerSupervisor
from free_claude_code.cli.local_admin import (
    LocalAdminError,
    apply_admin_values,
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
from free_claude_code.config.paths import server_log_path
from free_claude_code.config.provider_catalog import PROVIDER_CATALOG, ProviderAuthKind
from free_claude_code.config.settings import Settings, get_settings
from free_claude_code.learning.config import configured_profile, list_profiles
from free_claude_code.learning.reviewer_flow import reviewer_status

from . import codex_accounts
from .repo_picker import (
    RepoEntry,
    cache_path,
    default_roots,
    discover_repos,
    load_cached_repos,
    save_cached_repos,
)


@dataclass(frozen=True, slots=True)
class ControlResult:
    """One action that must temporarily leave the alternate-screen TUI."""

    action: str
    danger: bool = False
    profile: str | None = None
    repo: RepoEntry | None = None


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


class ControlCenterApp(App[ControlResult | None]):
    """Persistent GUI-like terminal shell over the existing control actions."""

    TITLE = "CodeSwitchyard"
    SUB_TITLE = "Control Center"

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

    #table {
        height: 1fr;
        margin: 0 1;
        background: $background;
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

    #input-value {
        margin-top: 1;
    }
    """

    BINDINGS = [
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
    ) -> None:
        super().__init__()
        self.settings = settings
        self.supervisor = supervisor
        self.selected_repo = selected_repo
        self.next_profile = next_profile or configured_profile()
        self.page = "dashboard"
        self.selected_provider: str | None = None
        self.selected_codex_profile: str | None = None
        self.selected_model: str | None = None
        self._oauth_provider: str | None = None
        self._oauth_last_state: str | None = None

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
                yield DataTable(id="table", cursor_type="row")
                yield VerticalScroll(id="content")
                yield Horizontal(id="actions")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#content").display = False
        self.set_interval(1.0, self._poll_live_state)
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
        await self._show_page(self.page, force=True)

    async def action_dashboard(self) -> None:
        nav = self.query_one("#nav", OptionList)
        nav.highlighted = 0
        await self._show_page("dashboard")

    async def _show_page(self, page: str, *, force: bool = False) -> None:
        if page not in {item[0] for item in self.NAV}:
            return
        if not force:
            self.selected_provider = None if page != "providers" else self.selected_provider
        self.page = page
        title = dict(self.NAV)[page]
        self.query_one("#page-title", Static).update(title)
        self._clear_actions()
        table = self.query_one("#table", DataTable)
        content = self.query_one("#content", VerticalScroll)
        table.clear(columns=True)
        table.display = page not in {"dashboard", "diagnose", "policy", "logs"}
        content.display = not table.display
        await content.remove_children()

        try:
            if page == "dashboard":
                await self._render_dashboard(content)
            elif page == "providers":
                self._render_providers(table)
            elif page == "accounts":
                self._render_accounts(table)
            elif page == "repos":
                self._render_repos(table)
            elif page == "profiles":
                self._render_profiles(table)
            elif page == "models":
                self._render_models(table)
            elif page == "reviewers":
                self._render_reviewers(table)
            elif page == "usage":
                self._render_usage(table)
            elif page == "diagnose":
                await self._render_diagnose(content)
            elif page == "policy":
                await self._render_policy(content)
            elif page == "logs":
                await self._render_logs(content)
            elif page == "settings":
                self._render_settings(table)
        except (LocalAdminError, OSError, ValueError) as exc:
            self.notify(str(exc), title="Control action failed", severity="error")

    async def _render_dashboard(self, content: VerticalScroll) -> None:
        owner = "this terminal" if self.supervisor is not None else "another process"
        status = (
            self.supervisor.status.value
            if self.supervisor is not None
            else ServerStatus.RUNNING.value
        )
        repo = self.selected_repo.display_path if self.selected_repo else Path.cwd().name
        codex = self._safe_codex_summary()
        text = (
            f"Server       {status} ({owner})\n"
            f"Repository   {repo}\n"
            f"Model        {self.settings.model}\n"
            f"Profile      {self.next_profile} (next launch)\n"
            f"FCC Account  {fcc_provider_account_summary()}\n"
            f"Codex Tools  {codex}\n"
            f"Context      {context_cap_tokens(os.environ):,} tokens"
        )
        self.query_one("#summary", Static).update(
            "Everything here is selectable; use arrows/mouse + Enter. "
            "No nested prompt menus."
        )
        await content.mount(Static(text, classes="dashboard-card"))
        self._add_action("refresh", "Refresh")

    def _render_providers(self, table: DataTable) -> None:
        self.query_one("#summary", Static).update(
            "Live connected-account state is overlaid on the config catalog."
        )
        table.add_columns("Provider", "Status", "Type")
        config = get_admin_config(self.settings)
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
                    live = connected_account_status(self.settings, provider_id)
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
        self._add_action("provider-open", "Open")
        self._add_action("provider-test", "Test")
        self._add_action("refresh", "Refresh")

    def _render_accounts(self, table: DataTable) -> None:
        self.query_one("#summary", Static).update(
            f"FCC Provider: {fcc_provider_account_summary()}   |   "
            f"Codex Tools: {self._safe_codex_summary()}"
        )
        table.add_columns("Codex profile", "Account", "Plan", "Active")
        for account in codex_accounts.list_accounts():
            table.add_row(
                account.profile,
                account.email or "connected",
                account.plan or "unknown",
                "●" if account.active else "",
                key=account.profile,
            )
        self._add_action("codex-switch", "Switch")
        self._add_action("codex-refresh", "Refresh usage")
        self._add_action("fcc-browser", "FCC login")
        self._add_action("fcc-device", "FCC device")

    def _render_repos(self, table: DataTable) -> None:
        repos = load_cached_repos(cache_path())
        self.query_one("#summary", Static).update(
            "Choose the repository used for the next Claude launch."
        )
        table.add_columns("Repository", "Branch", "Path")
        for repo in repos:
            table.add_row(repo.name, repo.branch, repo.display_path, key=repo.path)
        self._add_action("repo-select", "Select")
        self._add_action("repo-refresh", "Refresh")

    def _render_profiles(self, table: DataTable) -> None:
        profiles = list_profiles()
        active = configured_profile()
        self.query_one("#summary", Static).update(
            f"Running profile: {active}   |   Next launch: {self.next_profile}"
        )
        table.add_columns("Profile", "Running", "Next launch")
        for profile in profiles:
            table.add_row(
                profile,
                "●" if profile == active else "",
                "●" if profile == self.next_profile else "",
                key=profile,
            )
        self._add_action("profile-select", "Use next")

    def _render_models(self, table: DataTable) -> None:
        result = get_models(self.settings)
        models = result.get("models")
        labels = result.get("model_labels")
        evidence = result.get("model_evidence")
        self.query_one("#summary", Static).update(f"Current: {self.settings.model}")
        table.add_columns("Model", "ID", "Evidence")
        if isinstance(models, list):
            for raw in models:
                model = str(raw)
                friendly = model
                if isinstance(labels, dict) and isinstance(labels.get(model), str):
                    friendly = str(labels[model])
                source = ""
                if isinstance(evidence, dict) and isinstance(evidence.get(model), dict):
                    source = str(evidence[model].get("evidence_source", ""))
                table.add_row(friendly, model, source, key=model)
        self._add_action("model-select", "Use model")
        self._add_action("refresh", "Refresh")

    def _render_reviewers(self, table: DataTable) -> None:
        status = reviewer_status(profile=self.next_profile)
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
        self._add_action("refresh", "Refresh")

    def _render_usage(self, table: DataTable) -> None:
        result = get_usage(self.settings, days=30)
        self.query_one("#summary", Static).update("Local metadata-only usage · 30 days")
        table.add_columns("Metric", "Value")
        totals = result.get("totals")
        if isinstance(totals, Mapping):
            for key, value in totals.items():
                table.add_row(str(key), str(value))
        self._add_action("refresh", "Refresh")

    async def _render_diagnose(self, content: VerticalScroll) -> None:
        result = route_diagnostic(
            self.settings,
            model=self.settings.model,
            shapes=("text",),
            mode="strict",
        )
        self.query_one("#summary", Static).update("Current strict text route")
        await content.mount(Static(json.dumps(result, indent=2, sort_keys=True)))
        self._add_action("refresh", "Refresh")

    async def _render_policy(self, content: VerticalScroll) -> None:
        status = get_admin_status(self.settings)
        policy = status.get("session_policy", {})
        self.query_one("#summary", Static).update("Live session policy receipt")
        await content.mount(Static(json.dumps(policy, indent=2, sort_keys=True)))
        self._add_action("refresh", "Refresh")

    async def _render_logs(self, content: VerticalScroll) -> None:
        path = server_log_path()
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
        except OSError as exc:
            lines = [f"Log unavailable ({type(exc).__name__})"]
        self.query_one("#summary", Static).update(str(path))
        await content.mount(Static("\n".join(lines)))
        self._add_action("refresh", "Refresh")

    def _render_settings(self, table: DataTable) -> None:
        config = get_admin_config(self.settings)
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
        self._add_action("setting-edit", "Edit")
        self._add_action("refresh", "Refresh")

    def _clear_actions(self) -> None:
        actions = self.query_one("#actions", Horizontal)
        actions.remove_children()

    def _add_action(self, action_id: str, label: str) -> None:
        self.query_one("#actions", Horizontal).mount(Button(label, id=action_id))

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
                self.notify(f"Next launch repository: {repo.display_path}")
                await self._show_page("repos", force=True)
        elif self.page == "profiles":
            self.next_profile = value
            self.notify(f"Next launch profile: {value}")
            await self._show_page("profiles", force=True)
        elif self.page == "models":
            self.selected_model = value

    @on(Button.Pressed, "#provider-open")
    async def open_provider_button(self) -> None:
        table = self.query_one("#table", DataTable)
        if table.cursor_row >= 0 and table.row_count:
            key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key
            await self._show_provider_detail(str(key.value))

    async def _show_provider_detail(self, provider_id: str) -> None:
        self.selected_provider = provider_id
        table = self.query_one("#table", DataTable)
        table.clear(columns=True)
        table.add_columns("Field", "Value")
        descriptor = PROVIDER_CATALOG.get(provider_id)
        config = get_admin_config(self.settings)
        provider = self._provider_from_config(config, provider_id)
        name = str(provider.get("display_name", provider_id)) if provider else provider_id
        self.query_one("#page-title", Static).update(name)
        self._clear_actions()

        if descriptor is not None and descriptor.auth_kind is ProviderAuthKind.CONNECTED_ACCOUNT:
            status = connected_account_status(self.settings, provider_id)
            for key in ("state", "email", "model_count", "message"):
                value = status.get(key)
                if value not in (None, ""):
                    table.add_row(key.replace("_", " ").title(), str(value))
            self._add_action("fcc-browser", "Browser login")
            self._add_action("fcc-device", "Device login")
            if status.get("connected"):
                self._add_action("fcc-disconnect", "Disconnect")
            self._add_action("provider-test", "Test")
            self._add_action("provider-back", "Back")
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
        self._add_action("provider-field-edit", "Edit")
        self._add_action("provider-test", "Test")
        self._add_action("provider-back", "Back")

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
                return
            key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key
            provider_id = str(key.value)
        try:
            result = await asyncio.to_thread(test_provider, self.settings, provider_id)
        except LocalAdminError as exc:
            self.notify(str(exc), severity="error")
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
        self._oauth_provider = provider_id
        self._oauth_last_state = str(status.get("state", "connecting"))
        url = status.get("authorization_url") or status.get("verification_url")
        if isinstance(url, str) and url:
            webbrowser.open(url)
        code = status.get("user_code")
        if isinstance(code, str) and code:
            self.notify(f"Device code: {code}", title="OpenAI device login", timeout=15)
        else:
            self.notify("Browser opened. Waiting for OpenAI to finish…", title="FCC login")
        await self._show_provider_detail(provider_id)

    @on(Button.Pressed, "#fcc-disconnect")
    async def fcc_disconnect(self) -> None:
        provider_id = self.selected_provider or "openai"

        def callback(confirmed: bool | None) -> None:
            if confirmed:
                self.run_worker(self._disconnect_fcc(provider_id))

        self.push_screen(ConfirmModal("Disconnect the FCC provider account?"), callback)

    async def _disconnect_fcc(self, provider_id: str) -> None:
        try:
            await asyncio.to_thread(disconnect_connected_account, self.settings, provider_id)
        except LocalAdminError as exc:
            self.notify(str(exc), severity="error")
        else:
            self.notify("FCC provider account disconnected.")
            await self._show_provider_detail(provider_id)

    @on(Button.Pressed, "#provider-field-edit")
    async def provider_field_edit(self) -> None:
        provider_id = self.selected_provider
        if provider_id is None:
            return
        table = self.query_one("#table", DataTable)
        if not table.row_count:
            return
        key = str(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
        config = get_admin_config(self.settings)
        field = next(
            (
                item
                for item in config.get("fields", [])
                if isinstance(item, dict) and item.get("key") == key
            ),
            None,
        )
        if not isinstance(field, dict):
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
            result = await asyncio.to_thread(apply_admin_values, self.settings, {key: value})
        except LocalAdminError as exc:
            self.notify(str(exc), severity="error")
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
            return
        try:
            account = await asyncio.to_thread(codex_accounts.select_account, profile)
        except codex_accounts.CodexAccountError as exc:
            self.notify(str(exc), severity="error")
        else:
            self.notify(f"Codex Tools → {account.email or account.profile}")
            await self._show_page("accounts", force=True)

    @on(Button.Pressed, "#codex-refresh")
    async def codex_refresh(self) -> None:
        profile = self.selected_codex_profile or self._selected_table_key()
        if not profile:
            return
        try:
            await asyncio.to_thread(codex_accounts.refresh_usage, profile)
        except codex_accounts.CodexAccountError as exc:
            self.notify(str(exc), severity="error")
        else:
            self.notify(f"Refreshed {profile} usage.")
            await self._show_page("accounts", force=True)

    @on(Button.Pressed, "#repo-select")
    async def repo_select(self) -> None:
        path = self._selected_table_key()
        repo = self._repo_for_path(path) if path else None
        if repo is not None:
            self.selected_repo = repo
            self.notify(f"Next launch repository: {repo.display_path}")
            await self._show_page("repos", force=True)

    @on(Button.Pressed, "#repo-refresh")
    async def repo_refresh(self) -> None:
        self.notify("Scanning local repository roots…")
        repos = await asyncio.to_thread(discover_repos, default_roots())
        await asyncio.to_thread(save_cached_repos, repos, cache_path())
        self.notify(f"Found {len(repos)} repositories.")
        await self._show_page("repos", force=True)

    @on(Button.Pressed, "#profile-select")
    async def profile_select(self) -> None:
        profile = self._selected_table_key()
        if profile:
            self.next_profile = profile
            self.notify(f"Next launch profile: {profile}")
            await self._show_page("profiles", force=True)

    @on(Button.Pressed, "#model-select")
    async def model_select(self) -> None:
        model = self.selected_model or self._selected_table_key()
        if not model:
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
        if result.get("applied") is True:
            get_settings.cache_clear()
            self.settings.model = model
            self.notify(f"Model → {model}")
            await self._show_page("models", force=True)
        else:
            self.notify("Model update was rejected.", severity="error")

    @on(Button.Pressed, "#setting-edit")
    async def setting_edit(self) -> None:
        key = self._selected_table_key()
        if not key:
            return
        config = get_admin_config(self.settings)
        field = next(
            (
                item
                for item in config.get("fields", [])
                if isinstance(item, dict) and item.get("key") == key
            ),
            None,
        )
        if not isinstance(field, dict):
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
            result = await asyncio.to_thread(apply_admin_values, self.settings, {key: value})
        except LocalAdminError as exc:
            self.notify(str(exc), severity="error")
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
            if self.page == "dashboard":
                await self._show_page("dashboard", force=True)
            return
        try:
            status = connected_account_status(self.settings, provider_id)
        except LocalAdminError:
            return
        state = str(status.get("state", "unknown"))
        if state != self._oauth_last_state:
            self._oauth_last_state = state
            if state == "connected":
                email = status.get("email")
                suffix = f" · {email}" if isinstance(email, str) and email else ""
                self.notify(f"FCC account connected{suffix}", title="Login complete")
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
        table = self.query_one("#table", DataTable)
        if not table.row_count or table.cursor_row < 0:
            return None
        return str(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)

    def _repo_for_path(self, path: str) -> RepoEntry | None:
        return next((repo for repo in load_cached_repos(cache_path()) if repo.path == path), None)

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
        except codex_accounts.CodexAccountError:
            return "needs attention"


def run_control_tui(
    settings: Settings,
    *,
    supervisor: ServerSupervisor | None,
    launch_client: Callable[[bool, Sequence[str], Path | None], None],
) -> None:
    """Run the Harlequin-derived control shell and temporarily yield to Claude."""

    selected_repo: RepoEntry | None = None
    next_profile = configured_profile()
    while True:
        result = ControlCenterApp(
            settings,
            supervisor=supervisor,
            selected_repo=selected_repo,
            next_profile=next_profile,
        ).run()
        if result is None or result.action == "quit":
            return
        selected_repo = result.repo
        next_profile = result.profile or next_profile
        if result.action == "launch":
            argv: tuple[str, ...] = ()
            if next_profile != configured_profile():
                argv = ("--profile", next_profile)
            launch_client(
                result.danger,
                argv,
                Path(selected_repo.path) if selected_repo is not None else None,
            )
            continue
