"""Readability-first shell for the existing model-picker behavior."""

from collections.abc import Callable, Sequence
from pathlib import Path

from free_claude_code.cli.commands import ServerSupervisor
from free_claude_code.config.settings import Settings
from free_claude_code.learning.config import configured_profile

from .control_tui import _format_launch_failure
from .model_picker_tui import TuiuiControlCenterApp
from .repo_picker import RepoEntry


class ReadableModelControlCenterApp(TuiuiControlCenterApp):
    """Give the Models workspace the screen space its information needs."""

    CSS = (
        TuiuiControlCenterApp.CSS
        + """

    #model-list .model-list-row {
        height: 2;
        min-height: 2;
        padding: 0 1;
        content-align: left middle;
    }

    #model-inspector {
        width: 48%;
        min-width: 46;
        padding: 1 2;
    }

    #model-inspector-title {
        min-height: 2;
        color: $text;
        text-style: bold;
    }

    #model-inspector-status,
    #model-inspector-meta {
        color: $text;
    }
    """
    )

    async def _after_page_render(self, page: str, *, focus_target: str | None) -> None:
        await super()._after_page_render(page, focus_target=focus_target)
        models_page = page == "models"
        self.query_one("#sidebar").display = not models_page
        self.query_one("#summary").display = not models_page


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
