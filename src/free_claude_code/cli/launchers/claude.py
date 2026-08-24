"""Installed `fcc-claude` launcher."""

import os
import sys
from collections.abc import Sequence

from free_claude_code.cli.claude_env import (
    CLAUDE_BINARY_NAME,
    build_claude_proxy_env,
    resolved_model_id,
    settings_env_routing_conflict_message,
)
from free_claude_code.config.server_urls import local_proxy_root_url
from free_claude_code.config.settings import get_settings
from free_claude_code.learning.hooks import ensure_learning_hooks

from .common import preflight_proxy, resolve_client_binary, run_client_process

_DISPLAY_NAME = "Claude Code"
_INSTALL_HINT = "Install Claude Code with: npm install -g @anthropic-ai/claude-code"


def launch(argv: Sequence[str] | None = None) -> None:
    """Launch Claude Code with Free Claude Code proxy environment variables."""

    settings = get_settings()
    proxy_root_url = local_proxy_root_url(settings)
    if error := preflight_proxy(proxy_root_url):
        print(
            f"Free Claude Code proxy is not reachable at {proxy_root_url}: {error}",
            file=sys.stderr,
        )
        print("Start it in another terminal with: fcc-server", file=sys.stderr)
        raise SystemExit(1)

    try:
        ensure_learning_hooks()
    except (OSError, ValueError) as exc:
        print(
            f"FCC Learning hooks were not installed: {type(exc).__name__}",
            file=sys.stderr,
        )

    binary_name = claude_binary_name()
    binary_path = resolve_client_binary(
        binary_name=binary_name,
        display_name=_DISPLAY_NAME,
        install_hint=_INSTALL_HINT,
    )
    args = list(sys.argv[1:] if argv is None else argv)
    if conflict_message := settings_env_routing_conflict_message(
        os.environ,
        cwd=os.getcwd(),
        argv=args,
    ):
        print(conflict_message, file=sys.stderr)
        raise SystemExit(2)
    run_client_process(
        command=build_claude_launcher_command(binary_path=binary_path, argv=args),
        env=build_claude_proxy_env(
            proxy_root_url=proxy_root_url,
            auth_token=settings.anthropic_auth_token,
            base_env=os.environ,
            model_id=resolved_model_id(args, os.environ),
        ),
        binary_name=binary_name,
        display_name=_DISPLAY_NAME,
        install_hint=_INSTALL_HINT,
    )


def claude_binary_name() -> str:
    """Return the Claude Code binary name."""

    return CLAUDE_BINARY_NAME


def build_claude_launcher_command(
    *, binary_path: str, argv: Sequence[str]
) -> list[str]:
    """Return the Claude wrapper command without changing user arguments."""

    return [binary_path, *argv]
