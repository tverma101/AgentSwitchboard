"""Readability-first shell for the existing model-picker behavior."""

from collections.abc import Callable, Sequence
from pathlib import Path

from textual.widgets import DataTable, Static

from free_claude_code.cli.commands import ServerSupervisor
from free_claude_code.config.settings import Settings
from free_claude_code.learning.config import configured_profile

from .control_tui import _format_launch_failure
from .model_picker_tui import ModelListButton, TuiuiControlCenterApp
from .repo_picker import RepoEntry


class ReadableModelControlCenterApp(TuiuiControlCenterApp):
    """Keep model identity and actions visually dominant in the Models page."""

    CSS = (
        TuiuiControlCenterApp.CSS
        + """

    #model-list .model-list-row {
        height: 3;
        min-height: 3;
        padding: 0 1;
        content-align: left middle;
    }

    #model-inspector {
        width: 48%;
        min-width: 46;
        padding: 1 2;
    }

    #model-inspector-title {
        min-height: 3;
        color: $text;
        text-style: bold;
    }

    #model-inspector-status {
        color: $text;
        text-style: bold;
    }

    #model-inspector-meta {
        color: $text;
    }
    """
    )

    async def _after_page_render(
        self, page: str, *, focus_target: str | None
    ) -> None:
        await super()._after_page_render(page, focus_target=focus_target)
        models_page = page == "models"
        # The model browser is a workspace, not a dashboard card. Give it the
        # whole terminal instead of leaving a 22-column navigation rail and a
        # summary banner around the information the user is trying to read.
        self.query_one("#sidebar").display = not models_page
        self.query_one("#summary").display = not models_page

    async def _render_models(self, table: DataTable, *, refresh: bool = False) -> None:
        await super()._render_models(table, refresh=refresh)
        self._apply_readable_model_identity()

    def _refresh_model_editor_widgets(self) -> None:
        super()._refresh_model_editor_widgets()
        self._apply_readable_model_identity()

    def _apply_readable_model_identity(self) -> None:
        """Render friendly text and exact route identity as separate information."""
        for row in self.query(ModelListButton):
            model_ref = row.model_ref
            friendly = self._model_labels.get(model_ref, model_ref)
            default_mark = "★" if model_ref == self._model_pending_default else " "
            access_mark = "✓" if model_ref in self._model_pending_enabled else "○"
            price = self._model_prices.get(model_ref, "PRICE?")
            row.label = (
                f"{default_mark} {access_mark}  {friendly}\n"
                f"    {price:<6}  {model_ref}"
            )

        model_ref = self._model_inspector_ref
        if not model_ref:
            return
        friendly = self._model_labels.get(model_ref, model_ref)
        self.query_one("#model-inspector-title", Static).update(
            f"{friendly}\n{model_ref}"
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
