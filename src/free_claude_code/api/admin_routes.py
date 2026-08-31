"""Local admin UI routes and APIs."""

import ipaddress
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from free_claude_code.application.capabilities import Capability, CapabilityRoutingMode
from free_claude_code.application.connected_accounts import (
    ConnectedAccountLoginMode,
)
from free_claude_code.application.model_metadata import (
    CapabilityEvidenceStatus,
    ProviderModelInfo,
    ProviderModelRefreshResult,
)
from free_claude_code.application.route_diagnostics import build_route_diagnostic
from free_claude_code.application.tool_accounts import CodexToolAccountError
from free_claude_code.config.admin.manifest import FIELD_BY_KEY
from free_claude_code.config.admin.persistence import validate_updates
from free_claude_code.config.admin.values import load_config_response
from free_claude_code.config.model_labels import model_display_names
from free_claude_code.config.model_refs import configured_chat_model_refs
from free_claude_code.config.model_visibility import filter_cached_model_infos
from free_claude_code.config.provider_catalog import (
    PROVIDER_CATALOG,
    ProviderAuthKind,
)
from free_claude_code.learning.config import configured_profile
from free_claude_code.learning.reviewer_config import ReviewerPackSettings
from free_claude_code.learning.reviewer_flow import reviewer_status
from free_claude_code.learning.reviewer_scars import (
    ReviewerPack,
    ReviewerScarError,
    ScarRegistry,
    ScarState,
)
from free_claude_code.usage import tracking_summary

from .dependencies import get_services
from .ports import ApiServices

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent / "admin_static"
LOCAL_PROVIDER_PATHS = {
    "lmstudio": "/models",
    "llamacpp": "/models",
    "ollama": "/api/tags",
}


class AdminConfigPayload(BaseModel):
    """Partial config update submitted by the admin UI."""

    values: dict[str, Any] = Field(default_factory=dict)


class CustomProviderPayload(BaseModel):
    """Safe, narrow descriptor submitted by the local Admin surface."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    display_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    proxy: str | None = None
    local: bool | None = None
    models: list[str] | None = None
    enabled: bool | None = None


class AdminRouteDiagnosticPayload(BaseModel):
    """Synthetic shape only; raw prompts and content are not accepted."""

    model: str | None = Field(default=None, max_length=256, pattern=r"^[^\r\n]*$")
    shapes: tuple[str, ...] = Field(default=("text",), min_length=1, max_length=10)
    mode: CapabilityRoutingMode = CapabilityRoutingMode.STRICT


class ReviewerPackPayload(BaseModel):
    """Explicit enable/disable choice for one reviewer pack."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool


class ConnectedAccountLoginPayload(BaseModel):
    """Interactive connected-account login selection."""

    mode: ConnectedAccountLoginMode = ConnectedAccountLoginMode.BROWSER


def _is_loopback_host(host: str | None) -> bool:
    if host is None:
        return False
    normalized = host.strip().strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _origin_is_local(origin: str | None) -> bool:
    if not origin:
        return True
    parsed = urlsplit(origin)
    return _is_loopback_host(parsed.hostname)


def require_loopback_admin(request: Request) -> None:
    """Allow admin access only from the local machine."""

    client_host = request.client.host if request.client else None
    if not _is_loopback_host(client_host):
        raise HTTPException(status_code=403, detail="Admin UI is local-only")

    origin = request.headers.get("origin")
    if not _origin_is_local(origin):
        raise HTTPException(status_code=403, detail="Admin UI is local-only")


def _asset_response(filename: str) -> FileResponse:
    path = STATIC_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Admin asset not found")
    return FileResponse(path)


@router.get("/admin", include_in_schema=False)
async def admin_page(request: Request):
    require_loopback_admin(request)
    return _asset_response("index.html")


@router.get("/admin/assets/{filename}", include_in_schema=False)
async def admin_asset(filename: str, request: Request):
    require_loopback_admin(request)
    if filename not in {
        "admin.css",
        "admin.js",
        "admin-v2.css",
        "admin-ui-v2.js",
    }:
        raise HTTPException(status_code=404, detail="Admin asset not found")
    return _asset_response(filename)


@router.get("/admin/api/config")
async def get_admin_config(request: Request):
    require_loopback_admin(request)
    return load_config_response()


@router.post("/admin/api/config/validate")
async def validate_admin_config(payload: AdminConfigPayload, request: Request):
    require_loopback_admin(request)
    return validate_updates(_filtered_values(payload.values))


@router.post("/admin/api/config/apply")
async def apply_admin_config(
    payload: AdminConfigPayload,
    request: Request,
    background_tasks: BackgroundTasks,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    result = await services.admin.apply_admin_config(_filtered_values(payload.values))
    restart = result.get("restart")
    if isinstance(restart, dict) and restart.get("automatic"):
        background_tasks.add_task(services.admin.request_restart)
    return result


@router.get("/admin/api/status")
async def admin_status(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return services.admin.admin_status()


@router.post("/admin/api/diagnostics/route")
async def route_diagnostic(
    payload: AdminRouteDiagnosticPayload,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    """Explain a synthetic route from cached metadata without provider I/O."""
    require_loopback_admin(request)
    try:
        result = build_route_diagnostic(
            services.requests.current_settings(),
            runtime=services.requests,
            model=payload.model,
            shapes=payload.shapes,
            mode=payload.mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _no_store(result)


@router.get("/admin/api/providers/local-status")
async def local_provider_status(request: Request):
    require_loopback_admin(request)
    config = load_config_response()
    values = {field["key"]: field["value"] for field in config["fields"]}
    checks = []
    for provider_id, path in LOCAL_PROVIDER_PATHS.items():
        base_url = _local_provider_url(provider_id, values)
        checks.append(await _check_local_provider(provider_id, base_url, path))
    return {"providers": checks}


@router.post("/admin/api/providers/{provider_id}/test")
async def test_provider(
    provider_id: str,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return await services.admin.test_provider(provider_id)


@router.get("/admin/api/custom-providers")
async def custom_provider_status(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return _no_store({"providers": services.admin.custom_provider_status()})


@router.post("/admin/api/custom-providers")
async def add_custom_provider(
    payload: CustomProviderPayload,
    request: Request,
    background_tasks: BackgroundTasks,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    result = await services.admin.apply_custom_provider(
        payload.model_dump(exclude_unset=True)
    )
    _schedule_admin_restart(result, background_tasks, services)
    return _no_store(result)


@router.put("/admin/api/custom-providers/{provider_id}")
async def update_custom_provider(
    provider_id: str,
    payload: CustomProviderPayload,
    request: Request,
    background_tasks: BackgroundTasks,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    result = await services.admin.apply_custom_provider(
        payload.model_dump(exclude_unset=True),
        existing_provider_id=provider_id,
    )
    _schedule_admin_restart(result, background_tasks, services)
    return _no_store(result)


@router.delete("/admin/api/custom-providers/{provider_id}")
async def remove_custom_provider(
    provider_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    result = await services.admin.remove_custom_provider(provider_id)
    _schedule_admin_restart(result, background_tasks, services)
    return _no_store(result)


@router.get("/admin/api/providers/{provider_id}/auth")
async def connected_account_status(
    provider_id: str,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    _require_connected_account_provider(provider_id)
    status = await services.admin.connected_account_status(provider_id)
    return _no_store(status.as_dict())


@router.post("/admin/api/providers/{provider_id}/auth/login")
async def start_connected_account_login(
    provider_id: str,
    payload: ConnectedAccountLoginPayload,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    _require_connected_account_provider(provider_id)
    try:
        status = await services.admin.start_connected_account_login(
            provider_id, payload.mode
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(f"Could not start connected-account login ({type(exc).__name__})."),
        ) from exc
    return _no_store(status.as_dict())


@router.post("/admin/api/providers/{provider_id}/auth/cancel")
async def cancel_connected_account_login(
    provider_id: str,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    _require_connected_account_provider(provider_id)
    status = await services.admin.cancel_connected_account_login(provider_id)
    return _no_store(status.as_dict())


@router.delete("/admin/api/providers/{provider_id}/auth")
async def disconnect_connected_account(
    provider_id: str,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    _require_connected_account_provider(provider_id)
    status = await services.admin.disconnect_connected_account(provider_id)
    return _no_store(status.as_dict())


@router.get("/admin/api/tool-accounts")
async def codex_tool_accounts_status(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    """Return the installed Codex/helper account surface without credentials."""

    require_loopback_admin(request)
    return _no_store(await services.admin.codex_tool_accounts_status())


@router.post("/admin/api/tool-accounts/usage")
async def refresh_all_codex_tool_account_usage(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    """Refresh all Codex tool-account usage snapshots explicitly."""

    require_loopback_admin(request)
    try:
        result = await services.admin.refresh_all_codex_tool_account_usage()
    except CodexToolAccountError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _no_store(result)


@router.post("/admin/api/tool-accounts/{profile}/select")
async def select_codex_tool_account(
    profile: str,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    """Select a local Codex tool account without invoking OAuth."""

    require_loopback_admin(request)
    try:
        result = await services.admin.select_codex_tool_account(profile)
    except CodexToolAccountError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _no_store(result)


@router.post("/admin/api/tool-accounts/{profile}/usage")
async def refresh_codex_tool_account_usage(
    profile: str,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    """Refresh one local Codex tool account's metadata-only usage."""

    require_loopback_admin(request)
    try:
        result = await services.admin.refresh_codex_tool_account_usage(profile)
    except CodexToolAccountError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _no_store(result)


@router.delete("/admin/api/tool-accounts/{profile}")
async def forget_codex_tool_account(
    profile: str,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    """Forget a local Codex tool snapshot without upstream logout."""

    require_loopback_admin(request)
    try:
        result = await services.admin.forget_codex_tool_account(profile)
    except CodexToolAccountError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _no_store(result)


@router.get("/admin/api/models")
async def models(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    return _model_options(services)


@router.post("/admin/api/models/refresh")
async def refresh_models(
    request: Request,
    services: ApiServices = Depends(get_services),
):
    require_loopback_admin(request)
    result = await services.admin.refresh_models()
    return _model_options(services, refresh_result=result)


@router.get("/admin/api/usage")
async def usage(
    request: Request,
    days: int = Query(default=30, ge=1, le=366),
    services: ApiServices = Depends(get_services),
):
    """Return token usage buckets without exposing prompt or response content."""
    require_loopback_admin(request)
    if services.usage is None:
        return {
            "range_days": days,
            "from": None,
            "to": None,
            "totals": {},
            "daily": [],
            "models": [],
            "model_labels": {},
            "tracking": tracking_summary(),
        }
    summary = services.usage.summary(days)
    summary["model_labels"] = model_display_names(
        [row["model"] for row in summary["models"]]
    )
    return summary


@router.get("/admin/api/reviewer")
async def reviewer_controls(request: Request):
    """Return profile-local reviewer controls and compact scar metadata."""

    require_loopback_admin(request)
    try:
        return _no_store(reviewer_status(profile=configured_profile()))
    except (ReviewerScarError, ValueError) as exc:
        raise HTTPException(
            status_code=500, detail="Reviewer state is unavailable"
        ) from exc


@router.put("/admin/api/reviewer/packs/{pack}")
async def update_reviewer_pack(
    pack: ReviewerPack,
    payload: ReviewerPackPayload,
    request: Request,
):
    """Persist one explicit pack override for the current learning profile."""

    require_loopback_admin(request)
    try:
        ReviewerPackSettings(configured_profile()).set_override(pack, payload.enabled)
        return _no_store(reviewer_status(profile=configured_profile()))
    except (ReviewerScarError, ValueError) as exc:
        raise HTTPException(
            status_code=500, detail="Reviewer state is unavailable"
        ) from exc


@router.post("/admin/api/reviewer/scars/{scar_id}/forget")
async def forget_reviewer_scar(scar_id: str, request: Request):
    """Mark a scar stale while retaining its evidence and history."""

    return await _update_reviewer_scar_state(scar_id, ScarState.STALE, request)


@router.post("/admin/api/reviewer/scars/{scar_id}/supersede")
async def supersede_reviewer_scar(scar_id: str, request: Request):
    """Mark a scar superseded while retaining its evidence and history."""

    return await _update_reviewer_scar_state(scar_id, ScarState.SUPERSEDED, request)


async def _update_reviewer_scar_state(
    scar_id: str,
    state: ScarState,
    request: Request,
) -> JSONResponse:
    require_loopback_admin(request)
    try:
        record = ScarRegistry(configured_profile()).update_state(scar_id, state)
    except ReviewerScarError as exc:
        if str(exc).startswith("unknown reviewer scar id:"):
            raise HTTPException(
                status_code=404, detail="Reviewer scar not found"
            ) from exc
        raise HTTPException(
            status_code=500, detail="Reviewer state is unavailable"
        ) from exc
    return _no_store(record.as_dict())


def _model_options(
    services: ApiServices,
    *,
    refresh_result: ProviderModelRefreshResult | None = None,
) -> dict[str, object]:
    configured = {
        ref.model_ref
        for ref in configured_chat_model_refs(services.requests.current_settings())
    }
    discovered_infos = tuple(
        filter_cached_model_infos(
            services.requests.current_settings(),
            services.requests.cached_prefixed_model_infos(),
        )
    )
    catalog_infos = tuple(services.requests.cached_discovered_prefixed_model_infos())
    discovered = {info.model_id for info in discovered_infos}
    catalog = configured | {info.model_id for info in catalog_infos}
    failed_provider_ids = (
        refresh_result.failed_provider_ids if refresh_result is not None else ()
    )
    return {
        "models": sorted(configured | discovered, key=str.casefold),
        "model_labels": model_display_names(configured | discovered),
        "provider_status": _model_provider_statuses(services),
        "failed_providers": list(failed_provider_ids),
        "model_evidence": _model_evidence(configured, discovered_infos),
        "catalog_models": sorted(catalog, key=str.casefold),
        "catalog_model_labels": model_display_names(catalog),
        "catalog_model_evidence": _model_evidence(configured, catalog_infos),
    }


def _model_provider_statuses(services: ApiServices) -> list[dict[str, Any]]:
    """Expose the safe provider inventory alongside the model catalog.

    A provider can be configured before its first model-list request completes.
    The model rows intentionally remain cache-backed, but the picker still needs
    the provider inventory so that a configured provider is selectable and can
    show an actionable empty state instead of disappearing.
    """

    try:
        snapshot = services.admin.admin_status()
    except Exception:
        return []
    if not isinstance(snapshot, Mapping):
        return []
    raw_statuses = snapshot.get("provider_status")
    if not isinstance(raw_statuses, Sequence) or isinstance(raw_statuses, (str, bytes)):
        return []

    statuses: list[dict[str, Any]] = []
    seen_provider_ids: set[str] = set()
    for raw_status in raw_statuses:
        if not isinstance(raw_status, Mapping):
            continue
        provider_id = raw_status.get("provider_id")
        if not isinstance(provider_id, str):
            continue
        provider_id = provider_id.strip()
        if not provider_id or provider_id.casefold() in seen_provider_ids:
            continue
        seen_provider_ids.add(provider_id.casefold())
        status: dict[str, Any] = {"provider_id": provider_id}
        for key in ("display_name", "kind", "status", "label"):
            value = raw_status.get(key)
            if isinstance(value, str) and value.strip():
                status[key] = value.strip()
        statuses.append(status)
    return statuses


_MODEL_EVIDENCE_CAPABILITIES = (
    Capability.TEXT_INPUT,
    Capability.TEXT_OUTPUT,
    Capability.NATIVE_TOOLS,
    Capability.PARALLEL_TOOLS,
    Capability.NAMED_TOOL_CHOICE,
    Capability.REASONING_EFFORT,
    Capability.STRUCTURED_OUTPUT,
    Capability.VISION_INPUT,
    Capability.IMAGE_TOOL_RESULTS,
    Capability.SCREENSHOT_VISION,
)
_MODEL_EVIDENCE_STATUS_VALUES = frozenset(
    status.value for status in CapabilityEvidenceStatus
)


def _model_evidence(
    configured_model_ids: set[str],
    discovered_infos: tuple[ProviderModelInfo, ...],
) -> dict[str, object]:
    evidence = {
        info.model_id: _model_evidence_for_info(info) for info in discovered_infos
    }
    for model_id in configured_model_ids:
        evidence.setdefault(model_id, _model_evidence_for_info(None, model_id=model_id))
    return dict(sorted(evidence.items(), key=lambda item: item[0].casefold()))


def _model_evidence_for_info(
    info: ProviderModelInfo | None,
    *,
    model_id: str | None = None,
) -> dict[str, object]:
    if info is None:
        return {
            "model_id": model_id or "",
            "evidence_source": "unknown",
            "observed_at": None,
            "evidence_version": None,
            "evidence_protocol": None,
            "catalog_metadata": None,
            "is_free": None,
            "pricing": {},
            "capabilities": {
                capability.value: {
                    "state": CapabilityEvidenceStatus.UNKNOWN.value,
                    "confidence": "unknown",
                    "source": "unknown",
                }
                for capability in _MODEL_EVIDENCE_CAPABILITIES
            },
        }

    evidence = info.capability_evidence
    return {
        "model_id": info.model_id,
        "evidence_source": evidence.evidence_source,
        "observed_at": evidence.observed_at,
        "evidence_version": evidence.evidence_version,
        "evidence_protocol": evidence.evidence_protocol,
        "catalog_metadata": (
            info.catalog_metadata.as_dict()
            if info.catalog_metadata is not None
            else None
        ),
        "is_free": info.effective_is_free(),
        "pricing": dict(info.pricing),
        "capabilities": {
            capability.value: _capability_evidence_for_info(capability, info)
            for capability in _MODEL_EVIDENCE_CAPABILITIES
        },
    }


def _capability_evidence_for_info(
    capability: Capability,
    info: ProviderModelInfo,
) -> dict[str, str]:
    evidence = info.capability_evidence
    status = evidence.status_for(capability.value)
    source = evidence.evidence_source

    if status is CapabilityEvidenceStatus.UNKNOWN:
        if capability in {Capability.TEXT_INPUT, Capability.TEXT_OUTPUT}:
            status = CapabilityEvidenceStatus.SUPPORTED
            source = "protocol-baseline"
        elif capability is Capability.VISION_INPUT and info.supports_vision is not None:
            status = (
                CapabilityEvidenceStatus.SUPPORTED
                if info.supports_vision
                else CapabilityEvidenceStatus.UNSUPPORTED
            )
        elif capability is Capability.REASONING_EFFORT:
            reasoning_status = info.reasoning.status
            if reasoning_status.value in _MODEL_EVIDENCE_STATUS_VALUES:
                status = CapabilityEvidenceStatus(reasoning_status.value)
                source = info.reasoning.evidence_source
            elif info.supports_thinking is not None:
                status = (
                    CapabilityEvidenceStatus.SUPPORTED
                    if info.supports_thinking
                    else CapabilityEvidenceStatus.UNSUPPORTED
                )

    if status is CapabilityEvidenceStatus.UNKNOWN:
        source = "unknown"
    elif source == "unknown":
        source = "model_metadata"
    return {
        "state": status.value,
        "confidence": _confidence_for_evidence(status),
        "source": source,
    }


def _confidence_for_evidence(status: CapabilityEvidenceStatus) -> str:
    if status in {
        CapabilityEvidenceStatus.SUPPORTED,
        CapabilityEvidenceStatus.UNSUPPORTED,
    }:
        return "confirmed"
    if status is CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED:
        return "unverified"
    return "unknown"


def _filtered_values(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if key in FIELD_BY_KEY}


def _schedule_admin_restart(
    result: dict[str, Any],
    background_tasks: BackgroundTasks,
    services: ApiServices,
) -> None:
    restart = result.get("restart")
    if isinstance(restart, dict) and restart.get("automatic"):
        background_tasks.add_task(services.admin.request_restart)


def _local_provider_url(provider_id: str, values: dict[str, str]) -> str:
    if provider_id == "lmstudio":
        return values.get("LM_STUDIO_BASE_URL", "")
    if provider_id == "llamacpp":
        return values.get("LLAMACPP_BASE_URL", "")
    if provider_id == "ollama":
        return values.get("OLLAMA_BASE_URL", "")
    return ""


async def _check_local_provider(
    provider_id: str, base_url: str, path: str
) -> dict[str, Any]:
    clean_url = base_url.strip().rstrip("/")
    if not clean_url:
        return {
            "provider_id": provider_id,
            "status": "missing_url",
            "label": "Missing URL",
            "base_url": base_url,
        }

    url = f"{clean_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(url)
        ok = 200 <= response.status_code < 300
        return {
            "provider_id": provider_id,
            "status": "reachable" if ok else "offline",
            "label": "Reachable" if ok else "Offline",
            "base_url": base_url,
            "status_code": response.status_code,
        }
    except Exception as exc:
        return {
            "provider_id": provider_id,
            "status": "offline",
            "label": "Offline",
            "base_url": base_url,
            "error_type": type(exc).__name__,
        }


def _require_connected_account_provider(provider_id: str) -> None:
    descriptor = PROVIDER_CATALOG.get(provider_id)
    if (
        descriptor is None
        or descriptor.auth_kind is not ProviderAuthKind.CONNECTED_ACCOUNT
    ):
        raise HTTPException(
            status_code=404,
            detail="Provider does not support connected-account login.",
        )


def _no_store(payload: Any) -> JSONResponse:
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})
