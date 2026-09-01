"""First-class provider onboarding for the active Textual control center."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from free_claude_code.cli.local_admin import (
    LocalAdminError,
    apply_admin_values,
    apply_custom_provider,
    get_admin_config,
    remove_custom_provider,
    test_provider,
)

from .control_tui import ConfirmModal
from .model_picker_tui import TuiuiControlCenterApp


class CustomProviderModal(ModalScreen[dict[str, Any] | None]):
    """Collect one OpenAI-compatible provider without exposing raw JSON."""

    CSS = """
    CustomProviderModal {
        align: center middle;
        background: $background 70%;
    }

    #custom-provider-outer {
        width: 78;
        max-width: 94%;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: round $primary;
        background: $background;
    }

    #custom-provider-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #custom-provider-outer Label {
        margin-top: 1;
    }

    #custom-provider-buttons {
        height: 3;
        align-horizontal: right;
        margin-top: 1;
    }

    #custom-provider-buttons Button {
        width: 12;
        min-width: 10;
        height: 3;
        border: none;
        margin-left: 1;
    }
    """

    def __init__(self, provider: Mapping[str, Any] | None = None) -> None:
        super().__init__()
        self.provider = dict(provider or {})
        self.editing = bool(provider)

    def compose(self) -> ComposeResult:
        provider_id = str(self.provider.get("provider_id", ""))
        models = self.provider.get("model_ids")
        model_text = (
            ", ".join(str(model) for model in models)
            if isinstance(models, Sequence) and not isinstance(models, (str, bytes))
            else ""
        )
        with Vertical(id="custom-provider-outer"):
            yield Static(
                "Edit custom provider" if self.editing else "Add custom provider",
                id="custom-provider-title",
            )
            if not self.editing:
                yield Label("Provider ID")
                yield Input(
                    value=provider_id,
                    placeholder="my_gateway",
                    id="custom-provider-id",
                )
            else:
                yield Static(f"Provider ID: {provider_id}")
            yield Label("Display name")
            yield Input(
                value=str(self.provider.get("display_name", "")),
                placeholder="My Gateway",
                id="custom-provider-name",
            )
            yield Label("OpenAI-compatible base URL")
            yield Input(
                value=str(self.provider.get("base_url", "")),
                placeholder="https://example.com/v1",
                id="custom-provider-url",
            )
            yield Label("API key (blank keeps current when editing)")
            yield Input(password=True, id="custom-provider-key")
            yield Label("Proxy (optional; blank keeps current when editing)")
            yield Input(password=True, id="custom-provider-proxy")
            yield Label("Endpoint type")
            yield Select(
                [("Remote", "remote"), ("Local", "local")],
                value="local" if self.provider.get("local") is True else "remote",
                id="custom-provider-local",
            )
            yield Label("Fallback model IDs (optional, comma-separated)")
            yield Input(
                value=model_text,
                placeholder="model-a, model-b",
                id="custom-provider-models",
            )
            yield Label("State")
            yield Select(
                [("Enabled", "enabled"), ("Disabled", "disabled")],
                value=(
                    "disabled" if self.provider.get("enabled") is False else "enabled"
                ),
                id="custom-provider-enabled",
            )
            with Horizontal(id="custom-provider-buttons"):
                yield Button("Cancel", id="custom-provider-cancel")
                yield Button(
                    "Save & test", variant="primary", id="custom-provider-save"
                )

    @on(Button.Pressed, "#custom-provider-save")
    def save(self) -> None:
        values: dict[str, Any] = {
            "display_name": self.query_one(
                "#custom-provider-name", Input
            ).value.strip(),
            "base_url": self.query_one("#custom-provider-url", Input).value.strip(),
            "local": self.query_one("#custom-provider-local", Select).value == "local",
            "models": [
                value.strip()
                for value in self.query_one(
                    "#custom-provider-models", Input
                ).value.split(",")
                if value.strip()
            ],
            "enabled": (
                self.query_one("#custom-provider-enabled", Select).value == "enabled"
            ),
        }
        if not self.editing:
            values["id"] = self.query_one("#custom-provider-id", Input).value.strip()
        api_key = self.query_one("#custom-provider-key", Input).value.strip()
        proxy = self.query_one("#custom-provider-proxy", Input).value.strip()
        if api_key:
            values["api_key"] = api_key
        if proxy:
            values["proxy"] = proxy
        self.dismiss(values)

    @on(Button.Pressed, "#custom-provider-cancel")
    def cancel(self) -> None:
        self.dismiss(None)


class ProviderManagementControlCenterApp(TuiuiControlCenterApp):
    """Make provider setup, verification, and custom endpoints usable in-TUI."""

    async def _render_providers(self, table: DataTable) -> None:
        await super()._render_providers(table)
        await self._add_action("custom-provider-add", "Add custom")

    async def _render_provider_detail(self, provider_id: str) -> None:
        config = await asyncio.to_thread(get_admin_config, self.settings)
        if not isinstance(config, Mapping):
            raise TypeError("provider catalog returned an invalid response")
        provider = self._provider_from_config(config, provider_id)
        if not isinstance(provider, Mapping) or provider.get("custom") is not True:
            await super()._render_provider_detail(provider_id)
            return

        self.selected_provider = provider_id
        table = self.query_one("#table", DataTable)
        table.clear(columns=True)
        table.add_columns("Field", "Value")
        self.query_one("#page-title", Static).update(
            str(provider.get("display_name", provider_id))
        )
        self.query_one("#summary", Static).update(
            "Custom OpenAI-compatible provider. Secrets stay masked; Save & test "
            "verifies the model-list path and populates the picker."
        )
        await self._clear_actions()

        table.add_row("Provider ID", provider_id)
        table.add_row("Base URL", str(provider.get("base_url", "")))
        table.add_row(
            "API key",
            "configured" if provider.get("api_key_configured") else "missing",
        )
        table.add_row("Endpoint", "local" if provider.get("local") else "remote")
        table.add_row(
            "State",
            "enabled" if provider.get("enabled") is not False else "disabled",
        )
        model_ids = provider.get("model_ids")
        if isinstance(model_ids, Sequence) and not isinstance(model_ids, (str, bytes)):
            table.add_row(
                "Fallback models",
                ", ".join(str(model) for model in model_ids) or "none",
            )
        await self._add_action("custom-provider-edit", "Edit")
        await self._add_action(
            "custom-provider-toggle",
            "Disable" if provider.get("enabled") is not False else "Enable",
        )
        await self._add_action("provider-test", "Test")
        await self._add_action("custom-provider-remove", "Remove")
        await self._add_action("provider-back", "Back")

    @on(Button.Pressed, "#custom-provider-add")
    def custom_provider_add(self) -> None:
        def callback(values: dict[str, Any] | None) -> None:
            if values is not None:
                self.run_worker(self._save_custom_provider(values))

        self.push_screen(CustomProviderModal(), callback)

    @on(Button.Pressed, "#custom-provider-edit")
    async def custom_provider_edit(self) -> None:
        provider_id = self.selected_provider
        if provider_id is None:
            self._notify_missing_selection("custom provider")
            return
        provider = await self._custom_provider(provider_id)
        if provider is None:
            self.notify("Custom provider no longer exists.", severity="warning")
            await self._show_page("providers", force=True)
            return

        def callback(values: dict[str, Any] | None) -> None:
            if values is not None:
                self.run_worker(
                    self._save_custom_provider(values, existing_provider_id=provider_id)
                )

        self.push_screen(CustomProviderModal(provider), callback)

    @on(Button.Pressed, "#custom-provider-toggle")
    async def custom_provider_toggle(self) -> None:
        provider_id = self.selected_provider
        if provider_id is None:
            self._notify_missing_selection("custom provider")
            return
        provider = await self._custom_provider(provider_id)
        if provider is None:
            self.notify("Custom provider no longer exists.", severity="warning")
            await self._show_page("providers", force=True)
            return
        await self._save_custom_provider(
            {"enabled": provider.get("enabled") is False},
            existing_provider_id=provider_id,
            test_after_save=provider.get("enabled") is False,
        )

    @on(Button.Pressed, "#custom-provider-remove")
    def custom_provider_remove(self) -> None:
        provider_id = self.selected_provider
        if provider_id is None:
            self._notify_missing_selection("custom provider")
            return

        def callback(confirmed: bool | None) -> None:
            if confirmed:
                self.run_worker(self._remove_custom_provider(provider_id))

        self.push_screen(
            ConfirmModal(f"Remove custom provider {provider_id}?"),
            callback,
        )

    async def _custom_provider(self, provider_id: str) -> Mapping[str, Any] | None:
        try:
            config = await asyncio.to_thread(get_admin_config, self.settings)
        except Exception as exc:
            self._notify_action_error("Custom provider lookup failed", exc)
            return None
        if not isinstance(config, Mapping):
            return None
        provider = self._provider_from_config(config, provider_id)
        if isinstance(provider, Mapping) and provider.get("custom") is True:
            return provider
        return None

    async def _save_custom_provider(
        self,
        values: Mapping[str, Any],
        *,
        existing_provider_id: str | None = None,
        test_after_save: bool = True,
    ) -> None:
        try:
            result = await asyncio.to_thread(
                apply_custom_provider,
                self.settings,
                values,
                existing_provider_id=existing_provider_id,
            )
        except LocalAdminError as exc:
            self.notify(str(exc), title="Custom provider save failed", severity="error")
            return
        except Exception as exc:
            self._notify_action_error("Custom provider save failed", exc)
            return
        if not isinstance(result, Mapping):
            self.notify(
                "Custom provider save returned malformed data.",
                title="Custom provider save failed",
                severity="error",
            )
            return
        if result.get("applied") is not True:
            errors = result.get("errors")
            detail = (
                "; ".join(str(item) for item in errors)
                if isinstance(errors, Sequence) and not isinstance(errors, (str, bytes))
                else "Provider configuration was rejected."
            )
            self.notify(detail, title="Custom provider save failed", severity="error")
            return

        self._refresh_settings_snapshot()
        provider = result.get("provider")
        provider_id = existing_provider_id
        if isinstance(provider, Mapping):
            raw_id = provider.get("provider_id")
            if isinstance(raw_id, str) and raw_id:
                provider_id = raw_id
        if provider_id is None:
            raw_id = values.get("id")
            provider_id = raw_id if isinstance(raw_id, str) else None
        if not provider_id:
            self.notify(
                "Provider saved, but its ID was not returned.", severity="warning"
            )
            await self._show_page("providers", force=True)
            return

        if test_after_save and values.get("enabled", True) is not False:
            outcome = await self._test_provider_until_ready(provider_id)
            self._notify_provider_test(provider_id, outcome, prefix="Saved")
        else:
            self.notify(f"Saved {provider_id}.")
        await self._show_provider_detail(provider_id)

    async def _remove_custom_provider(self, provider_id: str) -> None:
        try:
            result = await asyncio.to_thread(
                remove_custom_provider, self.settings, provider_id
            )
        except LocalAdminError as exc:
            self.notify(
                str(exc), title="Custom provider removal failed", severity="error"
            )
            return
        except Exception as exc:
            self._notify_action_error("Custom provider removal failed", exc)
            return
        if not isinstance(result, Mapping) or result.get("applied") is not True:
            self.notify(
                f"Could not remove {provider_id}.",
                title="Custom provider removal failed",
                severity="error",
            )
            return
        self._refresh_settings_snapshot()
        self.selected_provider = None
        self.notify(f"Removed {provider_id}.")
        await self._show_page("providers", force=True)

    async def _apply_field(self, provider_id: str, key: str, value: str) -> None:
        """Save a built-in provider field and prove that discovery actually works."""

        try:
            result = await asyncio.to_thread(
                apply_admin_values, self.settings, {key: value}
            )
        except LocalAdminError as exc:
            self.notify(str(exc), title="Provider save failed", severity="error")
            return
        except Exception as exc:
            self._notify_action_error("Provider save failed", exc)
            return
        if not isinstance(result, Mapping):
            self.notify(
                f"{key} update returned malformed data.",
                title="Provider save failed",
                severity="error",
            )
            return
        if result.get("applied") is not True:
            self.notify(
                f"{key} was rejected.",
                title="Provider save failed",
                severity="error",
            )
            return

        self._refresh_settings_snapshot()
        outcome = await asyncio.to_thread(test_provider, self.settings, provider_id)
        self._notify_provider_test(provider_id, outcome, prefix=f"Saved {key}")
        await self._show_provider_detail(provider_id)

    @on(Button.Pressed, "#provider-test")
    async def provider_test_button(self) -> None:
        provider_id = self.selected_provider if self._provider_detail_open else None
        if provider_id is None:
            provider_id = self._table_row_key(self.query_one("#table", DataTable))
        if provider_id is None:
            self._notify_missing_selection("provider")
            return
        try:
            result = await asyncio.to_thread(test_provider, self.settings, provider_id)
        except LocalAdminError as exc:
            self.notify(str(exc), title="Provider test failed", severity="error")
            return
        except Exception as exc:
            self._notify_action_error("Provider test failed", exc)
            return
        self._notify_provider_test(provider_id, result)
        if isinstance(result, Mapping) and result.get("ok") is True:
            await self._show_provider_detail(provider_id)

    async def _test_provider_until_ready(self, provider_id: str) -> Mapping[str, Any]:
        """Bridge the intentional automatic restart used by custom-provider edits."""

        latest: Mapping[str, Any] = {"ok": False, "error_type": "Unavailable"}
        for attempt in range(12):
            if attempt:
                await asyncio.sleep(0.25)
            try:
                result = await asyncio.to_thread(
                    test_provider, self.settings, provider_id
                )
            except LocalAdminError:
                continue
            if not isinstance(result, Mapping):
                continue
            latest = result
            if result.get("ok") is True:
                return result
            error_type = str(result.get("error_type", ""))
            if error_type not in {
                "UnknownProviderError",
                "ApplicationUnavailableError",
            }:
                return result
        return latest

    def _notify_provider_test(
        self,
        provider_id: str,
        result: Mapping[str, Any] | object,
        *,
        prefix: str | None = None,
    ) -> None:
        lead = f"{prefix} · " if prefix else ""
        if not isinstance(result, Mapping):
            self.notify(
                f"{lead}{provider_id}: malformed provider-test response.",
                title="Provider test failed",
                severity="error",
            )
            return
        if result.get("ok") is True:
            models = result.get("models")
            count = (
                len(models)
                if isinstance(models, Sequence) and not isinstance(models, (str, bytes))
                else result.get("model_count", result.get("count", 0))
            )
            self.notify(
                f"{lead}{provider_id}: connected · {count} models discovered.",
                title="Provider ready",
            )
            return
        error_type = str(result.get("error_type", "ProviderError"))
        message = _provider_test_error_message(error_type)
        self.notify(
            f"{lead}{provider_id}: {message}",
            title="Provider test failed",
            severity="error",
        )


def _provider_test_error_message(error_type: str) -> str:
    """Turn the backend's redacted exception class into an actionable diagnosis."""

    normalized = error_type.casefold()
    if "authentication" in normalized or "permissiondenied" in normalized:
        return "authentication rejected; check the API key and account access."
    if "notfound" in normalized:
        return (
            "model-list endpoint was not found; check the base URL (/v1 compatibility)."
        )
    if "timeout" in normalized:
        return "provider timed out while listing models."
    if "connection" in normalized or "connecterror" in normalized:
        return "could not connect to the provider; check the URL, network, or proxy."
    if "modellistresponse" in normalized:
        return "provider returned a malformed model list."
    if "unknownprovider" in normalized:
        return "provider is not active yet; its restart did not finish."
    if "applicationunavailable" in normalized:
        return "provider runtime is restarting or unavailable."
    return f"provider test failed ({error_type})."
