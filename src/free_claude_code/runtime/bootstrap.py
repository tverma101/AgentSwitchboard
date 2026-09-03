"""Single production composition root for the FCC server."""

import asyncio
import json
import os
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from typing import Any

from free_claude_code.api.app import create_app
from free_claude_code.api.ports import ApiServices
from free_claude_code.application.helpers import ApprovedHelperRegistry
from free_claude_code.application.session_policy import (
    build_session_execution_policy_for_settings,
)
from free_claude_code.config.custom_providers import provider_registry_for_settings
from free_claude_code.config.logging_config import configure_logging
from free_claude_code.config.paths import server_log_path, usage_db_path
from free_claude_code.config.settings import Settings, get_settings
from free_claude_code.messaging.transcription import TranscriptionService
from free_claude_code.messaging.voice import Transcriber
from free_claude_code.providers.admission import ProviderAdmissionController
from free_claude_code.providers.base import BaseProvider, ProviderConfig
from free_claude_code.providers.nvidia_nim.voice import NvidiaNimTranscriber
from free_claude_code.providers.openai_codex import (
    OpenAIAuthManager,
    OpenAICodexProvider,
)
from free_claude_code.providers.runtime import ProviderRuntime
from free_claude_code.providers.runtime.factory import ProviderFactory, create_provider
from free_claude_code.providers.runtime.model_metadata_catalog import (
    ModelMetadataCatalog,
)
from free_claude_code.runtime.codex_computer_use_helper import (
    CodexComputerUseHelperAdapter,
)
from free_claude_code.usage import UsageStore

from .application import ApplicationRuntime, RestartCallback
from .asgi import RuntimeASGIApp
from .codex_catalog import CodexModelCatalogPublisher
from .codex_tool_accounts import CodexToolAccountsRuntime
from .provider_manager import ProviderRuntimeManager


def build_asgi_app(
    settings: Settings,
    restart_callback: RestartCallback | None = None,
) -> RuntimeASGIApp:
    """Construct the complete server application and its resource owner."""
    log_path = Path(os.getenv("LOG_FILE", server_log_path()))
    configure_logging(
        log_path,
        level=settings.log_level,
        verbose_third_party=settings.log_raw_api_payloads,
    )
    openai_auth = OpenAIAuthManager(proxy=settings.openai_proxy)
    openai_factory = partial(_create_openai_provider, auth=openai_auth)
    helper_registry, helper_adapter = _build_approved_helper_registry()
    runtime_factory = partial(
        _build_provider_runtime,
        openai_factory=openai_factory,
        helper_registry=helper_registry,
    )
    provider_manager = ProviderRuntimeManager(
        settings,
        runtime_factory=runtime_factory,
        connected_provider_ids=openai_auth.connected_provider_ids,
        model_catalog_publisher=CodexModelCatalogPublisher(),
        model_metadata_catalog=ModelMetadataCatalog.from_settings(settings),
    )
    runtime = ApplicationRuntime(
        provider_manager,
        transcriber=_create_transcriber(settings),
        restart_callback=restart_callback,
        connected_accounts={"openai": openai_auth},
        codex_tool_accounts=CodexToolAccountsRuntime(),
        approved_helper_registry=helper_registry,
        helper_cleanup=helper_adapter.close,
    )
    services = ApiServices(
        requests=provider_manager,
        admin=runtime,
        tasks=runtime,
        usage=UsageStore(
            usage_db_path(),
            account_fingerprint_resolver=lambda provider_id: (
                openai_auth.usage_account_fingerprint()
                if provider_id == openai_auth.provider_id
                else None
            ),
        ),
    )
    return RuntimeASGIApp(create_app(services), runtime)


def _build_approved_helper_registry() -> tuple[
    ApprovedHelperRegistry, CodexComputerUseHelperAdapter
]:
    """Register reviewed helpers without probing the host or the network."""

    adapter = CodexComputerUseHelperAdapter()
    registry = ApprovedHelperRegistry()
    registry.register(adapter.approved_helper())
    registry.freeze()
    return registry, adapter


def _build_provider_runtime(
    settings: Settings,
    *,
    openai_factory: ProviderFactory,
    helper_registry: ApprovedHelperRegistry,
) -> ProviderRuntime:
    """Build one provider generation with its shared policy guard."""

    policy = build_session_execution_policy_for_settings(settings, helper_registry)
    provider_constructor = partial(
        create_provider,
        injected_factories={"openai": openai_factory},
        registry=provider_registry_for_settings(settings),
        egress_guard=policy.egress_guard,
    )
    return ProviderRuntime(
        settings,
        provider_constructor=provider_constructor,
        session_policy=policy,
    )


def _create_openai_provider(
    config: ProviderConfig,
    _settings: Settings,
    admission: ProviderAdmissionController,
    *,
    auth: OpenAIAuthManager,
) -> BaseProvider:
    return OpenAICodexProvider(
        config,
        auth=auth,
        admission=admission,
        # The model-scoped Codex dialect is now available to both local FCC
        # modes.  Sandbox-only behavior remains limited to the Claude client
        # context window in the launcher.
        responses_lite_enabled=True,
    )


def _create_transcriber(settings: Settings) -> Transcriber | None:
    if not settings.voice_note_enabled:
        return None
    if settings.whisper_device == "nvidia_nim":
        return NvidiaNimTranscriber(
            model=settings.whisper_model,
            api_key=settings.nvidia_nim_api_key,
        )
    return TranscriptionService(
        model=settings.whisper_model,
        device=settings.whisper_device,
        huggingface_api_key=settings.huggingface_api_key,
    )


BOOTSTRAP_VERSION = 1
_BOOTSTRAP_MODEL_KEYS = frozenset(
    {
        "MODEL",
        "MODEL_CATALOG_MODE",
        "MODEL_CATALOG_ALLOWLIST",
        "MODEL_ALIASES",
    }
)


def _bootstrap_repository_payload(repo: Any) -> dict[str, Any]:
    """Return display-safe repository metadata for the native TUI."""

    return {
        "name": repo.name,
        "path": repo.path,
        "branch": repo.branch,
        "remote": repo.remote,
        "last_used": repo.last_used,
        "display_path": repo.display_path,
        "repository_name": repo.repository_name,
        "identity": repo.identity,
        "selection_detail": repo.selection_detail,
    }


async def _build_prelaunch_state(settings: Settings) -> dict[str, Any]:
    """Discover models without starting Uvicorn or opening an HTTP socket."""

    from free_claude_code.api.admin_routes import _model_options
    from free_claude_code.api.ports import ApiServices
    from free_claude_code.config.admin.values import load_config_response
    from free_claude_code.core.repository_inventory import load_repository_inventory

    asgi_app = build_asgi_app(settings)
    runtime = asgi_app.runtime
    try:
        manager = runtime.provider_manager
        refresh_result = await manager.refresh_model_list_cache()
        services = ApiServices(requests=manager, admin=runtime, tasks=runtime)
        model_options = _model_options(services, refresh_result=refresh_result)
        config = load_config_response()
        # Connected-account state comes from the short-lived runtime; retain it
        # in the same safe provider inventory the live Admin route publishes.
        config["provider_status"] = model_options["provider_status"]
        repositories, selected_path = await asyncio.to_thread(load_repository_inventory)
        return {
            "version": BOOTSTRAP_VERSION,
            "config": config,
            "models": model_options,
            "status": {
                "status": "prelaunch",
                "host": settings.host,
                "port": settings.port,
                "model": settings.model,
                "pending_fields": [],
            },
            "custom_providers": runtime.custom_provider_status(),
            "local_status": [],
            "usage": None,
            "diagnostic": None,
            "repositories": {
                "repositories": [
                    _bootstrap_repository_payload(repo) for repo in repositories
                ],
                "selected_path": selected_path,
            },
        }
    finally:
        await runtime.close()


def build_bootstrap_state(
    settings: Settings,
    *,
    launch_after_repository: bool = False,
    launch_danger: bool = False,
) -> dict[str, Any]:
    """Build serverless state consumed by the Rust TUI.

    Direct ``fcc-claude`` launches carry their client intent into the snapshot
    instead of asking the TUI to invent a second server-start workflow.  The
    flags are UI orchestration metadata only; credentials remain in the
    managed settings source and never enter the snapshot.
    """

    state = asyncio.run(_build_prelaunch_state(settings))
    state["launch_after_repository"] = launch_after_repository
    state["launch_danger"] = launch_danger
    return state


def write_bootstrap_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically publish a private bootstrap snapshot."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def read_bootstrap_result(path: Path) -> dict[str, Any]:
    """Read and validate the native TUI's write-back envelope."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(
            "The control center exited without saving its choices"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("The control center returned an unreadable result") from exc
    if not isinstance(payload, dict) or payload.get("version") != BOOTSTRAP_VERSION:
        raise RuntimeError("The control center returned an unsupported result version")
    values = payload.get("values", {})
    if not isinstance(values, dict) or any(not isinstance(key, str) for key in values):
        raise RuntimeError("The control center returned invalid configuration changes")
    selected = payload.get("selected_repository")
    if selected is not None and not isinstance(selected, str):
        raise RuntimeError(
            "The control center returned an invalid repository selection"
        )
    if not isinstance(payload.get("start_server"), bool):
        raise RuntimeError(
            "The control center did not state whether to start the server"
        )
    return payload


def _verify_bootstrap_values(values: Mapping[str, Any]) -> None:
    """Read the effective config back after the atomic managed-file commit."""

    from free_claude_code.config.admin.manifest import FIELD_BY_KEY
    from free_claude_code.config.admin.sources import is_locked_source
    from free_claude_code.config.admin.values import (
        load_config_response,
        load_value_state,
        normalize_for_env,
    )

    state = load_value_state()
    for key, expected in values.items():
        if key not in FIELD_BY_KEY:
            raise RuntimeError(f"Prelaunch returned an unknown field: {key}")
        entry = state.get(key)
        if entry is None or is_locked_source(entry["source"]):
            raise RuntimeError(f"Prelaunch returned a locked field: {key}")
        if normalize_for_env(entry["value"]) != normalize_for_env(expected):
            raise RuntimeError(f"Prelaunch save read-back failed for {key}")

    if _BOOTSTRAP_MODEL_KEYS.intersection(values):
        config = load_config_response()
        fields = {field["key"] for field in config["fields"]}
        for key in _BOOTSTRAP_MODEL_KEYS.intersection(values):
            if key not in fields:
                raise RuntimeError(f"Model save read-back omitted {key}")


def _validate_bootstrap_keys(values: Mapping[str, Any]) -> None:
    """Reject unknown or externally locked fields before any file is changed."""

    from free_claude_code.config.admin.manifest import FIELD_BY_KEY
    from free_claude_code.config.admin.sources import is_locked_source
    from free_claude_code.config.admin.values import load_value_state

    state = load_value_state()
    for key in values:
        if not isinstance(key, str) or key not in FIELD_BY_KEY:
            raise RuntimeError(f"Prelaunch returned an unknown field: {key}")
        if is_locked_source(state[key]["source"]):
            raise RuntimeError(f"Prelaunch returned a locked field: {key}")


def apply_bootstrap_result(payload: Mapping[str, Any]) -> Settings:
    """Persist TUI choices, verify them, and return freshly loaded settings."""

    from free_claude_code.config.admin.persistence import (
        commit_prepared_admin_update,
        prepare_admin_update,
    )
    from free_claude_code.core.repository_inventory import (
        select_repository as select_local_repository,
    )

    values = payload.get("values", {})
    if not isinstance(values, Mapping):
        raise RuntimeError("Prelaunch configuration changes are not a mapping")
    if values:
        _validate_bootstrap_keys(values)
        prepared = prepare_admin_update(values)
        if not prepared.valid:
            detail = "; ".join(prepared.errors) or "invalid configuration"
            raise RuntimeError(f"Prelaunch choices were rejected: {detail}")
        commit_prepared_admin_update(prepared)
        _verify_bootstrap_values(values)

    selected_path = payload.get("selected_repository")
    if selected_path:
        try:
            _selected_repo, persisted = select_local_repository(selected_path)
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"Repository selection could not be saved: {exc}"
            ) from exc
        if not persisted:
            raise RuntimeError("Repository selection could not be persisted")

    get_settings.cache_clear()
    # The CLI has already performed its owned-file migrations before entering
    # this prelaunch phase. Reload the settings directly here so the runtime
    # composition root never imports back into the CLI facade (which would
    # create a cycle through the bootstrap helpers re-exported by commands).
    return get_settings()
