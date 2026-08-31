"""Reliability policy for the interactive model picker."""

import time
from collections.abc import Callable, Sequence
from pathlib import Path

from textual.widgets import Static

from free_claude_code.cli.commands import ServerSupervisor
from free_claude_code.config.settings import Settings
from free_claude_code.learning.config import configured_profile

from .control_tui import _format_launch_failure
from .model_picker_tui import TuiuiControlCenterApp
from .repo_picker import RepoEntry

MODEL_PICKER_CACHE_SECONDS = 1.0


class ReliableModelControlCenterApp(TuiuiControlCenterApp):
    """Keep model-picker state fresh without turning filtering into provider I/O."""

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
        self._model_picker_snapshot_at = 0.0

    async def _load_model_catalog(self, *, refresh: bool = False) -> dict[str, object]:
        """Re-read the server snapshot after a short UI cache interval."""

        now = time.monotonic()
        if refresh or now - self._model_picker_snapshot_at >= MODEL_PICKER_CACHE_SECONDS:
            self._model_catalog_result = None
        result = await super()._load_model_catalog(refresh=refresh)
        self._model_picker_snapshot_at = time.monotonic()
        return result

    def _refresh_settings_snapshot(self) -> None:
        """Drop the model snapshot whenever canonical settings are reloaded."""

        super()._refresh_settings_snapshot()
        self._model_catalog_result = None
        self._model_picker_snapshot_at = 0.0

    def _update_model_editor_summary(self) -> None:
        """Keep unavailable saved defaults visible instead of implying a healthy row."""

        super()._update_model_editor_summary()
        default = self._model_pending_default
        if default is None or default in self._model_known_refs:
            return
        self._model_summary_text = f"{self._model_summary_text}   •   default unavailable"
        self.query_one("#summary", Static).update(self._model_summary_text)


def run_control_tui(
    settings: Settings,
    *,
    supervisor: ServerSupervisor | None,
    launch_client: Callable[[bool, Sequence[str], Path | None], None],
    startup_error: str | None = None,
) -> None:
    """Run the control center with the reliable model-picker policy."""

    selected_repo: RepoEntry | None = None
    server_profile = configured_profile()
    next_profile = server_profile
    while True:
        app = ReliableModelControlCenterApp(
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
