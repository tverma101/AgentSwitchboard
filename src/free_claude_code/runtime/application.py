"""Single owner for application startup, shutdown, and runtime operations."""

import asyncio
import inspect
import logging
import os
import traceback
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any

from loguru import logger

import free_claude_code.cli.managed as cli_managed
import free_claude_code.messaging.session as messaging_session
import free_claude_code.messaging.workflow as messaging_workflow_module
from free_claude_code.application.connected_accounts import (
    ConnectedAccountLoginMode,
    ConnectedAccountPort,
    ConnectedAccountState,
    ConnectedAccountStatus,
)
from free_claude_code.application.errors import ApplicationUnavailableError
from free_claude_code.application.helpers import ApprovedHelperRegistry
from free_claude_code.application.model_metadata import ProviderModelRefreshResult
from free_claude_code.application.ports import StopResult
from free_claude_code.application.tool_accounts import (
    CodexToolAccountError,
    CodexToolAccountsPort,
)
from free_claude_code.config.admin.persistence import (
    PreparedAdminUpdate,
    commit_prepared_admin_update,
    prepare_admin_update,
)
from free_claude_code.config.admin.status import provider_config_status
from free_claude_code.config.admin.values import load_value_state
from free_claude_code.config.custom_providers import (
    CUSTOM_PROVIDERS_ENV,
    parse_custom_provider_json,
    remove_custom_provider_json,
    sanitize_provider_id,
    update_custom_provider_json,
)
from free_claude_code.config.env_files import (
    ANTHROPIC_AUTH_TOKEN_ENV,
    process_env_key_is_effective,
)
from free_claude_code.config.model_refs import parse_provider_type
from free_claude_code.config.paths import messaging_state_dir_path
from free_claude_code.config.provider_catalog import PROVIDER_CATALOG
from free_claude_code.config.server_urls import local_admin_url, local_proxy_root_url
from free_claude_code.config.settings import Settings, get_settings
from free_claude_code.messaging.platforms import factory as messaging_platform_factory
from free_claude_code.messaging.platforms.factory import MessagingPlatformOptions
from free_claude_code.messaging.platforms.ports import (
    MessagingPlatformComponents,
    MessagingRuntime,
)
from free_claude_code.messaging.voice import Transcriber

from .provider_manager import ProviderRuntimeManager

RestartCallback = Callable[[], Awaitable[None] | None]


async def best_effort(
    name: str,
    awaitable: Awaitable[Any],
    *,
    log_verbose_errors: bool = False,
) -> bool:
    """Run one cleanup step and report whether it completed.

    The lifecycle owner intentionally applies no generic timeout here. Cancelling
    an arbitrary cleanup at a deadline can abandon a half-closed SDK, thread, or
    provider resource; resource-specific cleanup or the process supervisor owns
    any force-termination deadline.
    """
    try:
        await awaitable
    except Exception as exc:
        if log_verbose_errors:
            logger.warning(
                "Shutdown step failed: {}: {}: {}",
                name,
                type(exc).__name__,
                exc,
            )
        else:
            logger.warning(
                "Shutdown step failed: {}: exc_type={}",
                name,
                type(exc).__name__,
            )
        return False
    return True


def warn_if_process_auth_token(settings: Settings) -> None:
    """Warn when server auth was implicitly inherited from the shell."""
    model_config = getattr(settings, "model_config", Settings.model_config)
    if process_env_key_is_effective(model_config, ANTHROPIC_AUTH_TOKEN_ENV):
        logger.warning(
            "ANTHROPIC_AUTH_TOKEN is set in the process environment but not in "
            "a configured .env file. The proxy will require that token. Add "
            "ANTHROPIC_AUTH_TOKEN= to .env to disable proxy auth, or set the "
            "same token in .env to make server auth explicit."
        )


def startup_failure_message(settings: Settings, exc: Exception) -> str:
    """Return the existing concise ASGI startup failure message."""
    if isinstance(exc, ApplicationUnavailableError):
        return exc.message.strip() or "Server startup failed."
    if settings.log_api_error_tracebacks:
        return f"{type(exc).__name__}: {exc}"
    return f"Server startup failed: exc_type={type(exc).__name__}"


class ApplicationRuntime:
    """Own every process-lifetime resource used by one server instance."""

    def __init__(
        self,
        provider_manager: ProviderRuntimeManager,
        *,
        transcriber: Transcriber | None,
        restart_callback: RestartCallback | None = None,
        connected_accounts: Mapping[str, ConnectedAccountPort] | None = None,
        codex_tool_accounts: CodexToolAccountsPort | None = None,
        approved_helper_registry: ApprovedHelperRegistry | None = None,
        helper_cleanup: Callable[[], None] | None = None,
    ) -> None:
        self.provider_manager = provider_manager
        self._transcriber = transcriber
        self._restart_callback = restart_callback
        self._connected_accounts = dict(connected_accounts or {})
        self._codex_tool_accounts = codex_tool_accounts
        self._approved_helper_registry = approved_helper_registry
        self._helper_cleanup = helper_cleanup
        self._helper_closed = False
        self._connected_account_revisions = {
            provider_id: manager.status().revision
            for provider_id, manager in self._connected_accounts.items()
        }
        self._config_lock = asyncio.Lock()
        self._pending_fields: list[str] = []
        self._messaging_runtime: MessagingRuntime | None = None
        self._messaging_workflow: messaging_workflow_module.MessagingWorkflow | None = (
            None
        )
        self._cli_manager: cli_managed.ManagedClaudeSessionManager | None = None
        self._started = False
        self._closed = False
        self._provider_manager_closed = False
        self._connected_accounts_closed = False
        self._close_lock = asyncio.Lock()

    @property
    def settings(self) -> Settings:
        return self.provider_manager.current_settings()

    @property
    def is_closed(self) -> bool:
        """Whether this runtime released its complete ownership graph."""
        return self._closed

    async def start(self) -> None:
        if self._started:
            return
        logger.info("Starting Claude Code Proxy...")
        try:
            warn_if_process_auth_token(self.settings)
            await self.provider_manager.warm_referenced_model_cache()
            self.provider_manager.start_model_list_refresh()
            await self._start_messaging_if_configured()
            logging.getLogger("uvicorn.error").info(
                "FCC control endpoint: %s (terminal-only; browser launch disabled)",
                local_admin_url(self.settings),
            )
            self._started = True
        except asyncio.CancelledError:
            await self.close()
            raise
        except Exception as exc:
            logger.error(
                "Startup failed:\n{}",
                startup_failure_message(self.settings, exc),
            )
            await self.close()
            raise

    async def close(self) -> bool:
        async with self._close_lock:
            if self._closed:
                return True
            logger.info("Shutdown requested, cleaning up...")
            self._closed = await self._close_owned_resources()
            if self._closed:
                self._started = False
                logger.info("Server shut down cleanly")
            else:
                logger.warning(
                    "Server shutdown incomplete; owned resources remain for retry"
                )
            return self._closed

    async def apply_admin_config(
        self,
        updates: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Apply one validated config update without splitting runtime ownership."""
        async with self._config_lock:
            prepared = prepare_admin_update(updates)
            if not prepared.valid:
                return prepared.applied_response()
            assert prepared.settings is not None

            if prepared.pending_fields:
                result = self._commit_admin_update(prepared)
                restart = self._restart_metadata(
                    prepared.pending_fields,
                    prepared.settings,
                )
                result["restart"] = restart
                self._pending_fields = (
                    [] if restart["automatic"] else list(prepared.pending_fields)
                )
                return result

            result: dict[str, Any] = {}

            def commit() -> None:
                result.update(self._commit_admin_update(prepared))

            await self.provider_manager.replace(
                prepared.settings,
                commit=commit,
                reason="admin_apply",
            )
            self._pending_fields = []
            result["restart"] = self._restart_metadata((), prepared.settings)
            return result

    def admin_status(self) -> dict[str, Any]:
        settings = self.settings
        session_policy = self.provider_manager.current_session_policy()
        return {
            "status": "running",
            "host": settings.host,
            "port": settings.port,
            "model": settings.model,
            "provider": parse_provider_type(settings.model),
            "pending_fields": list(self._pending_fields),
            "provider_status": self._provider_status(),
            "session_policy": (
                session_policy.receipt() if session_policy is not None else None
            ),
            "cached_models": {
                provider_id: sorted(model_ids)
                for provider_id, model_ids in self.provider_manager.cached_model_ids().items()
            },
        }

    def _provider_status(self) -> list[dict[str, Any]]:
        """Return config status with live connected-account state overlaid.

        ``provider_config_status`` intentionally has no runtime dependencies,
        so a connected account would otherwise always be reported as
        ``disconnected`` even while its process-lifetime auth manager holds
        credentials or is completing an interactive login. Keep the static
        configuration fields intact and overlay only the safe lifecycle state
        owned by the running manager.
        """

        statuses = provider_config_status(load_value_state())
        by_provider = {
            str(status.get("provider_id", "")).casefold(): status
            for status in statuses
            if status.get("provider_id")
        }
        for provider_id, manager in self._connected_accounts.items():
            status = by_provider.get(provider_id.casefold())
            if status is None:
                continue
            account = manager.status()
            if account.state is ConnectedAccountState.CONNECTED:
                status.update(status="connected", label="Connected")
            elif account.state is ConnectedAccountState.CONNECTING:
                status.update(status="connecting", label="Signing in")
            elif account.state is ConnectedAccountState.ERROR:
                status.update(status="error", label="Authentication error")
            else:
                status.update(status="disconnected", label="Not connected")
        return statuses

    async def test_provider(self, provider_id: str) -> dict[str, Any]:
        lease = await self.provider_manager.acquire()
        try:
            provider = lease.resolve_provider(provider_id)
            infos = await provider.list_model_infos()
        except Exception as exc:
            return {
                "provider_id": provider_id,
                "ok": False,
                "error_type": type(exc).__name__,
            }
        finally:
            await lease.release()
        await self.provider_manager.cache_model_infos_with_metadata(provider_id, infos)
        return {
            "provider_id": provider_id,
            "ok": True,
            "models": sorted(info.model_id for info in infos),
        }

    def custom_provider_status(self) -> list[dict[str, Any]]:
        """Return configured custom providers without exposing secrets."""
        statuses = provider_config_status(load_value_state())
        return [
            status
            for status in statuses
            if status["provider_id"] not in PROVIDER_CATALOG
        ]

    async def apply_custom_provider(
        self,
        values: Mapping[str, Any],
        *,
        existing_provider_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate and persist one custom provider through the normal Admin path."""
        raw = str(load_value_state().get(CUSTOM_PROVIDERS_ENV, {}).get("value", ""))
        try:
            updated = update_custom_provider_json(
                raw,
                values,
                existing_provider_id=existing_provider_id,
            )
        except ValueError as exc:
            return {
                "applied": False,
                "valid": False,
                "errors": [str(exc)],
                "pending_fields": [],
            }
        result = await self.apply_admin_config({CUSTOM_PROVIDERS_ENV: updated})
        if result.get("applied"):
            requested_id = existing_provider_id or values.get("id")
            descriptor = next(
                (
                    item
                    for item in parse_custom_provider_json(updated)
                    if requested_id is not None
                    and item.provider_id == sanitize_provider_id(requested_id)
                ),
                None,
            )
            if descriptor is not None:
                result["provider"] = descriptor.public_dict()
        return result

    async def remove_custom_provider(self, provider_id: str) -> dict[str, Any]:
        """Remove one custom provider through the normal restart-aware Admin path."""
        raw = str(load_value_state().get(CUSTOM_PROVIDERS_ENV, {}).get("value", ""))
        try:
            updated = remove_custom_provider_json(raw, provider_id)
        except ValueError as exc:
            return {
                "applied": False,
                "valid": False,
                "errors": [str(exc)],
                "pending_fields": [],
            }
        return await self.apply_admin_config({CUSTOM_PROVIDERS_ENV: updated})

    async def refresh_models(self) -> ProviderModelRefreshResult:
        return await self.provider_manager.refresh_model_list_cache()

    async def connected_account_status(
        self, provider_id: str
    ) -> ConnectedAccountStatus:
        """Return safe account state and synchronize model availability."""

        manager = self._connected_account(provider_id)
        status = manager.status()
        previous_revision = self._connected_account_revisions.get(provider_id)
        if status.revision != previous_revision:
            await self.provider_manager.connected_provider_changed(
                provider_id, connected=status.connected
            )
            self._connected_account_revisions[provider_id] = status.revision
        model_count = len(self.provider_manager.cached_model_ids().get(provider_id, ()))
        return replace(status, model_count=model_count)

    async def start_connected_account_login(
        self,
        provider_id: str,
        mode: ConnectedAccountLoginMode,
    ) -> ConnectedAccountStatus:
        """Start one provider-owned interactive login."""

        return await self._connected_account(provider_id).start_login(mode)

    async def cancel_connected_account_login(
        self, provider_id: str
    ) -> ConnectedAccountStatus:
        """Cancel one pending provider login."""

        return await self._connected_account(provider_id).cancel_login()

    async def disconnect_connected_account(
        self, provider_id: str
    ) -> ConnectedAccountStatus:
        """Disconnect an account and evict only that provider's models."""

        status = await self._connected_account(provider_id).disconnect()
        await self.provider_manager.connected_provider_changed(
            provider_id, connected=False
        )
        self._connected_account_revisions[provider_id] = status.revision
        return status

    async def codex_tool_accounts_status(self) -> dict[str, Any]:
        """Return local Codex tool-account state without exposing credentials."""

        if self._codex_tool_accounts is None:
            return {
                "available": False,
                "state": "unavailable",
                "accounts": [],
                "message": "Codex tool account management is unavailable in this runtime.",
            }
        return await asyncio.to_thread(self._codex_tool_accounts.status)

    async def select_codex_tool_account(self, profile: str) -> dict[str, Any]:
        """Switch the installed Codex helper account locally."""

        return await self._run_codex_tool_account_operation(
            lambda manager: manager.select(profile)
        )

    async def refresh_codex_tool_account_usage(self, profile: str) -> dict[str, Any]:
        """Refresh one installed Codex helper account's metadata-only usage."""

        return await self._run_codex_tool_account_operation(
            lambda manager: manager.refresh_usage(profile)
        )

    async def refresh_all_codex_tool_account_usage(self) -> dict[str, Any]:
        """Refresh all installed Codex helper account usage snapshots."""

        return await self._run_codex_tool_account_operation(
            lambda manager: manager.refresh_all_usage()
        )

    async def forget_codex_tool_account(self, profile: str) -> dict[str, Any]:
        """Forget one local Codex helper snapshot without upstream logout."""

        return await self._run_codex_tool_account_operation(
            lambda manager: manager.forget(profile)
        )

    async def _run_codex_tool_account_operation(
        self,
        operation: Callable[[CodexToolAccountsPort], dict[str, Any]],
    ) -> dict[str, Any]:
        manager = self._codex_tool_accounts
        if manager is None:
            raise CodexToolAccountError(
                "Codex tool account management is unavailable in this runtime."
            )
        return await asyncio.to_thread(operation, manager)

    async def request_restart(self) -> None:
        callback = self._restart_callback
        if callback is None:
            return
        result = callback()
        if inspect.isawaitable(result):
            await result

    async def stop_all(self) -> StopResult | None:
        if self._messaging_workflow is not None:
            outcome = await self._messaging_workflow.stop_all_tasks()
            return StopResult(cancelled_count=outcome.cancelled_count)
        if self._cli_manager is not None:
            await self._cli_manager.stop_all()
            return StopResult(source="cli_manager")
        return None

    def _commit_admin_update(
        self,
        prepared: PreparedAdminUpdate,
    ) -> dict[str, Any]:
        result = commit_prepared_admin_update(prepared)
        get_settings.cache_clear()
        return result

    def _restart_metadata(
        self,
        fields: tuple[str, ...],
        settings: Settings,
    ) -> dict[str, Any]:
        automatic = bool(fields and self._restart_callback is not None)
        return {
            "required": bool(fields),
            "automatic": automatic,
            "admin_url": local_admin_url(settings) if automatic else None,
            "fields": list(fields),
        }

    async def _start_messaging_if_configured(self) -> None:
        try:
            components = messaging_platform_factory.create_messaging_components(
                self.settings.messaging_platform,
                self._messaging_options(),
            )
            if components is not None:
                await self._start_messaging_workflow(components)
        except ImportError as exc:
            cleaned = await self._cleanup_messaging()
            if self.settings.log_api_error_tracebacks:
                logger.warning("Messaging module import error: {}", exc)
            else:
                logger.warning(
                    "Messaging module import error: exc_type={}",
                    type(exc).__name__,
                )
            if not cleaned:
                raise RuntimeError("Messaging startup cleanup incomplete") from exc
        except Exception as exc:
            cleaned = await self._cleanup_messaging()
            if self.settings.log_api_error_tracebacks:
                logger.error("Failed to start messaging platform: {}", exc)
                logger.error(traceback.format_exc())
            else:
                logger.error(
                    "Failed to start messaging platform: exc_type={}",
                    type(exc).__name__,
                )
            if not cleaned:
                raise RuntimeError("Messaging startup cleanup incomplete") from exc

    def _messaging_options(self) -> MessagingPlatformOptions:
        settings = self.settings
        return MessagingPlatformOptions(
            telegram_bot_token=settings.telegram_bot_token,
            allowed_telegram_user_id=settings.allowed_telegram_user_id,
            telegram_proxy_url=settings.telegram_proxy_url,
            discord_bot_token=settings.discord_bot_token,
            allowed_discord_channels=settings.allowed_discord_channels,
            transcriber=self._transcriber,
            messaging_rate_limit=settings.messaging_rate_limit,
            messaging_rate_window=settings.messaging_rate_window,
            log_raw_messaging_content=settings.log_raw_messaging_content,
            log_messaging_error_details=settings.log_messaging_error_details,
            log_api_error_tracebacks=settings.log_api_error_tracebacks,
        )

    async def _start_messaging_workflow(
        self,
        components: MessagingPlatformComponents,
    ) -> None:
        settings = self.settings
        self._messaging_runtime = components.runtime
        workspace = (
            os.path.abspath(settings.allowed_dir)
            if settings.allowed_dir
            else os.getcwd()
        )
        os.makedirs(workspace, exist_ok=True)
        data_path = os.path.abspath(messaging_state_dir_path())
        os.makedirs(data_path, exist_ok=True)
        allowed_dirs = [workspace] if settings.allowed_dir else []

        self._cli_manager = cli_managed.ManagedClaudeSessionManager(
            workspace_path=workspace,
            proxy_root_url=local_proxy_root_url(settings),
            allowed_dirs=allowed_dirs,
            auth_token=settings.anthropic_auth_token,
            log_raw_cli_diagnostics=settings.log_raw_cli_diagnostics,
            log_messaging_error_details=settings.log_messaging_error_details,
            session_policy=self.provider_manager.current_session_policy(),
            approved_helper_registry=self._approved_helper_registry,
        )
        session_store = messaging_session.SessionStore(
            storage_path=os.path.join(data_path, "sessions.json"),
            managed_message_cap=settings.max_message_log_entries_per_chat,
        )
        workflow = messaging_workflow_module.MessagingWorkflow(
            platform_name=components.name,
            outbound=components.outbound,
            voice_cancellation=components.voice_cancellation,
            cli_manager=self._cli_manager,
            session_store=session_store,
            debug_platform_edits=settings.debug_platform_edits,
            debug_subagent_stack=settings.debug_subagent_stack,
            log_raw_cli_diagnostics=settings.log_raw_cli_diagnostics,
            log_messaging_error_details=settings.log_messaging_error_details,
        )
        self._messaging_workflow = workflow
        workflow.restore()
        components.runtime.on_message(workflow.handle_message)
        await components.runtime.start()
        await workflow.repair_restored_statuses()
        if components.startup_notice is not None:
            await workflow.publish_startup_notice(components.startup_notice)
        logger.info("{} platform started with messaging workflow", components.name)

    async def _close_owned_resources(self) -> bool:
        if not await self._cleanup_messaging():
            return False
        if not await self._cleanup_transcriber():
            return False
        if not await self._cleanup_helper_runtime():
            return False
        verbose = self.settings.log_api_error_tracebacks
        if not self._provider_manager_closed:
            self._provider_manager_closed = await best_effort(
                "provider_manager.close",
                self.provider_manager.close(),
                log_verbose_errors=verbose,
            )
            if not self._provider_manager_closed:
                return False
        if self._connected_accounts_closed:
            return True
        results = await asyncio.gather(
            *(
                best_effort(
                    f"connected_account.{provider_id}.close",
                    manager.close(),
                    log_verbose_errors=verbose,
                )
                for provider_id, manager in self._connected_accounts.items()
            )
        )
        self._connected_accounts_closed = all(results)
        return self._connected_accounts_closed

    def _connected_account(self, provider_id: str) -> ConnectedAccountPort:
        manager = self._connected_accounts.get(provider_id)
        if manager is None:
            raise ApplicationUnavailableError(
                f"Provider {provider_id!r} does not support connected-account login."
            )
        return manager

    async def _cleanup_messaging(self) -> bool:
        verbose = self.settings.log_api_error_tracebacks
        workflow = self._messaging_workflow
        runtime = self._messaging_runtime
        cli_manager = self._cli_manager

        if runtime is not None:
            quiesced = await best_effort(
                "messaging_runtime.quiesce",
                runtime.quiesce(),
                log_verbose_errors=verbose,
            )
            if not quiesced:
                # Delivery must remain available until ingress is known stopped.
                # Retaining the graph lets the next close retry this exact gate.
                return False

        if workflow is not None:
            closed = await best_effort(
                "messaging_workflow.close",
                workflow.close(),
                log_verbose_errors=verbose,
            )
            if not closed:
                # Active workflow tasks may still need delivery, transcription,
                # CLI sessions, and providers while a later close retries drain.
                return False
            if self._messaging_workflow is workflow:
                self._messaging_workflow = None
            if self._cli_manager is cli_manager:
                self._cli_manager = None
        elif cli_manager is not None:
            drained = await best_effort(
                "cli_manager.stop_all",
                cli_manager.stop_all(),
                log_verbose_errors=verbose,
            )
            if not drained:
                return False
            if self._cli_manager is cli_manager:
                self._cli_manager = None

        if runtime is not None:
            closed = await best_effort(
                "messaging_runtime.close",
                runtime.close(),
                log_verbose_errors=verbose,
            )
            if not closed:
                return False
            if self._messaging_runtime is runtime:
                self._messaging_runtime = None
        return True

    async def _cleanup_transcriber(self) -> bool:
        transcriber = self._transcriber
        if transcriber is None:
            return True
        closed = await best_effort(
            "transcriber.close",
            transcriber.close(),
            log_verbose_errors=self.settings.log_api_error_tracebacks,
        )
        if closed and self._transcriber is transcriber:
            self._transcriber = None
        return closed

    async def _cleanup_helper_runtime(self) -> bool:
        """Close the optional native helper host after sessions have drained."""

        if self._helper_closed or self._helper_cleanup is None:
            return True
        try:
            self._helper_cleanup()
        except Exception as exc:
            logger.warning(
                "Shutdown step failed: approved_helper.close: exc_type={}",
                type(exc).__name__,
            )
            return False
        self._helper_closed = True
        return True
