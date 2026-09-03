"""Readability-first shell for the existing model-picker behavior."""

from collections.abc import Callable, Sequence
from pathlib import Path

from textual.widgets import Static

from free_claude_code.cli.commands import ServerSupervisor
from free_claude_code.config.settings import Settings
from free_claude_code.learning.config import configured_profile

from .control_tui import _format_launch_failure
from .model_picker_tui import ModelListButton, _model_provider_id
from .provider_management_tui import ProviderManagementControlCenterApp
from .repo_picker import RepoEntry


def _compact_exact_ref(model_ref: str, *, limit: int = 62) -> str:
    """Keep both the routing prefix and variant-bearing tail visible."""

    if len(model_ref) <= limit:
        return model_ref
    left = max(12, limit // 3)
    right = max(18, limit - left - 1)
    return f"{model_ref[:left]}…{model_ref[-right:]}"


def _readable_row_label(row: ModelListButton) -> str:
    """Render human name and exact model identity as separate information."""

    default_mark = "★" if row._is_default else " "
    access_mark = "✓" if row._enabled else "○"
    friendly = " ".join(row.friendly.split()) or row.model_ref
    identity = _compact_exact_ref(row.model_ref)
    return f"{default_mark} {access_mark}  {friendly}\n     {identity}    {row.price}"


def _readable_inspector_title(friendly: str, model_ref: str) -> str:
    """Never let a friendly label hide the exact routable model."""

    friendly = " ".join(friendly.split()) or model_ref
    return f"{friendly}\n{model_ref}"


class ReadableModelControlCenterApp(ProviderManagementControlCenterApp):
    """Give model identity the screen space it needs to remain obvious."""

    CSS = (
        ProviderManagementControlCenterApp.CSS
        + """

    #model-browser {
        width: 58%;
        min-width: 0;
    }

    #model-list .model-list-row {
        height: 3;
        min-height: 3;
        padding: 0 1;
        content-align: left middle;
    }

    #model-inspector {
        width: 42%;
        min-width: 0;
        padding: 1 2;
    }

    #model-inspector-title {
        min-height: 3;
        padding: 0 0 1 0;
        color: $text;
        text-style: bold;
    }

    #model-inspector-status {
        min-height: 2;
        color: $text;
        text-style: bold;
    }

    #model-inspector-meta {
        min-height: 9;
        color: $text;
    }

    #model-inspector-hint {
        color: $text-muted;
    }
    """
    )

    def _refresh_model_editor_widgets(self) -> None:
        super()._refresh_model_editor_widgets()
        for row in self.query(ModelListButton):
            row.label = _readable_row_label(row)

    def _update_model_inspector(self) -> None:
        super()._update_model_inspector()
        model = self._model_inspector_ref
        if model is None or model not in self._model_known_refs:
            return

        friendly = self._model_labels.get(model, model)
        self.query_one("#model-inspector-title", Static).update(
            _readable_inspector_title(friendly, model)
        )
        self.query_one("#model-inspector-meta", Static).update(
            "\n".join(
                (
                    "EXACT MODEL REF",
                    model,
                    "",
                    f"Provider   {_model_provider_id(model)}",
                    f"Price      {self._model_prices.get(model, 'PRICE?')}",
                    f"Source     {self._model_sources.get(model, 'unknown')}",
                )
            )
        )
        self.query_one("#model-inspector-hint", Static).update(
            "Friendly names are display-only. The exact ref above is what Claude routes."
        )


def run_control_tui(
    settings: Settings,
    *,
    supervisor: ServerSupervisor | None,
    launch_client: Callable[[bool, Sequence[str], Path | None], None],
    startup_error: str | None = None,
) -> None:
    """Run the readability-first model control center."""

    selected_repo: RepoEntry | None = None
    server_profile = configured_profile()
    next_profile = server_profile
    while True:
        app = ReadableModelControlCenterApp(
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
