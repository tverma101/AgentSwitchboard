"""Efficient, best-effort enrichment from the public models.dev catalog."""

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from free_claude_code.application.model_metadata import (
    CapabilityEvidence,
    CapabilityEvidenceStatus,
    ModelCatalogMetadata,
    ProviderModelInfo,
    ReasoningCapabilityEvidence,
    ReasoningCapabilityStatus,
)
from free_claude_code.config.paths import model_metadata_catalog_path

MODELS_DEV_API_URL = "https://models.dev/api.json"
CATALOG_SCHEMA_VERSION = 1
MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 100_000
FETCH_TIMEOUT_SECONDS = 10.0
FETCH_RETRY_COOLDOWN_SECONDS = 300.0

PayloadFetcher = Callable[[], Awaitable[bytes]]
Clock = Callable[[], datetime]


# models.dev uses public-provider names while FCC keeps stable, provider-specific
# ids. Local providers intentionally have no entry here: their own model-list
# endpoint is the source of truth and they must not trigger an internet request.
_MODELS_DEV_PROVIDER_ALIASES: dict[str, tuple[str, ...]] = {
    "nvidia_nim": ("nvidia", "nvidia-nim"),
    "openai": ("openai",),
    "azure_openai": ("azure", "openai"),
    "open_router": ("openrouter", "open_router"),
    "gemini": ("google", "gemini"),
    "vertex": ("google", "vertex"),
    "deepseek": ("deepseek",),
    "mistral": ("mistral",),
    "mistral_codestral": ("mistral", "codestral"),
    "opencode_zen": ("opencode",),
    "opencode_go": ("opencode-go", "opencode_go"),
    "vercel": ("vercel",),
    "bedrock": ("amazon-bedrock", "bedrock"),
    "huggingface": ("huggingface",),
    "cohere": ("cohere",),
    "github_models": ("github-models", "github_models"),
    "wafer": ("wafer",),
    "kimi": ("moonshotai", "kimi"),
    "kimi_code": ("moonshotai", "kimi"),
    "kilo": ("kilo",),
    "minimax": ("minimax",),
    "cerebras": ("cerebras",),
    "groq": ("groq",),
    "sambanova": ("sambanova",),
    "fireworks": ("fireworks-ai", "fireworks"),
    "cloudflare": ("cloudflare",),
    "zai": ("zai",),
    "ollama_cloud": ("ollama",),
}


class ModelMetadataCatalog:
    """Cache one full models.dev snapshot and enrich discovered model ids.

    A provider refresh supplies all of its model ids at once. This class then
    performs at most one bounded catalog fetch per TTL window, parses the full
    source once, and persists only JSON-safe metadata. A catalog outage never
    blocks provider discovery; provider-native metadata remains usable.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        fetch_enabled: bool = True,
        ttl_hours: float = 24.0,
        fetch_payload: PayloadFetcher | None = None,
        now: Clock | None = None,
        persistence_enabled: bool = True,
    ) -> None:
        if ttl_hours <= 0:
            raise ValueError("ttl_hours must be positive")
        self._path = path or model_metadata_catalog_path()
        self._fetch_enabled = fetch_enabled
        self._ttl = timedelta(hours=ttl_hours)
        self._fetch_payload = fetch_payload
        self._now = now or _utcnow
        self._persistence_enabled = persistence_enabled
        self._records: dict[tuple[str, str], ModelCatalogMetadata] = {}
        self._source_version: str | None = None
        self._fetched_at: datetime | None = None
        self._last_fetch_attempt_at: datetime | None = None
        self._loaded = False
        self._refresh_lock = asyncio.Lock()

    @classmethod
    def from_settings(cls, settings: Any) -> ModelMetadataCatalog:
        """Build the production catalog from settings without accepting a URL."""

        return cls(
            fetch_enabled=bool(
                getattr(settings, "model_metadata_catalog_enabled", False)
            ),
            ttl_hours=float(
                getattr(settings, "model_metadata_catalog_ttl_hours", 24.0)
            ),
        )

    async def enrich_model_infos(
        self,
        infos_by_provider: Mapping[str, Iterable[ProviderModelInfo]],
    ) -> dict[str, frozenset[ProviderModelInfo]]:
        """Return provider model infos enriched from one shared snapshot."""

        normalized = {
            provider_id: tuple(model_infos)
            for provider_id, model_infos in infos_by_provider.items()
        }
        if not normalized:
            return {}

        self._load_once()
        if self._should_fetch(normalized):
            async with self._refresh_lock:
                self._load_once()
                if self._should_fetch(normalized):
                    await self._refresh()

        return {
            provider_id: frozenset(
                self._enrich_info(provider_id, info) for info in model_infos
            )
            for provider_id, model_infos in normalized.items()
        }

    def _should_fetch(
        self,
        infos_by_provider: Mapping[str, Iterable[ProviderModelInfo]],
    ) -> bool:
        if not self._fetch_enabled or not self._has_catalog_provider(infos_by_provider):
            return False
        now = self._now()
        if self._last_fetch_attempt_at is not None:
            since_attempt = now - self._last_fetch_attempt_at
            if since_attempt < timedelta(
                seconds=min(self._ttl.total_seconds(), FETCH_RETRY_COOLDOWN_SECONDS)
            ):
                return False
        return self._fetched_at is None or now - self._fetched_at >= self._ttl

    @staticmethod
    def _has_catalog_provider(
        infos_by_provider: Mapping[str, Iterable[ProviderModelInfo]],
    ) -> bool:
        return any(
            provider_id in _MODELS_DEV_PROVIDER_ALIASES and model_infos
            for provider_id, model_infos in infos_by_provider.items()
        )

    async def _refresh(self) -> None:
        attempted_at = self._now()
        self._last_fetch_attempt_at = attempted_at
        try:
            payload = await (
                self._fetch_payload()
                if self._fetch_payload is not None
                else self._fetch_from_models_dev()
            )
            if len(payload) > MAX_PAYLOAD_BYTES:
                raise ValueError("models.dev response exceeded the safe size limit")
            source_version = hashlib.sha256(payload).hexdigest()[:16]
            records = _parse_models_dev_payload(
                payload,
                source_version=source_version,
                observed_at=_format_timestamp(attempted_at),
            )
            if not records:
                raise ValueError("models.dev response contained no model records")
            self._records = records
            self._source_version = source_version
            self._fetched_at = attempted_at
            self._write_cache()
            logger.info(
                "Model metadata catalog refreshed: records={} version={}",
                len(records),
                source_version,
            )
        except Exception as exc:
            logger.warning(
                "Model metadata catalog refresh skipped: reason={}",
                type(exc).__name__,
            )

    async def _fetch_from_models_dev(self) -> bytes:
        timeout = httpx.Timeout(
            FETCH_TIMEOUT_SECONDS,
            connect=min(FETCH_TIMEOUT_SECONDS, 5.0),
        )
        async with (
            httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
            ) as client,
            client.stream(
                "GET",
                MODELS_DEV_API_URL,
                headers={"Accept": "application/json"},
            ) as response,
        ):
            response.raise_for_status()
            content_length = _positive_int(response.headers.get("content-length"))
            if content_length is not None and content_length > MAX_PAYLOAD_BYTES:
                raise ValueError("models.dev response exceeded the safe size limit")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_PAYLOAD_BYTES:
                    raise ValueError("models.dev response exceeded the safe size limit")
                chunks.append(chunk)
            return b"".join(chunks)

    def _load_once(self) -> None:
        if self._loaded or not self._persistence_enabled:
            return
        self._loaded = True
        try:
            payload = self._path.read_bytes()
            if len(payload) > MAX_PAYLOAD_BYTES:
                return
            document = json.loads(payload)
        except OSError, ValueError, TypeError:
            return
        if not isinstance(document, Mapping):
            return
        if document.get("schema_version") != CATALOG_SCHEMA_VERSION:
            return
        records = document.get("records")
        if not isinstance(records, list):
            return
        loaded_records: dict[tuple[str, str], ModelCatalogMetadata] = {}
        for item in records[:MAX_RECORDS]:
            if not isinstance(item, Mapping):
                continue
            provider = _string_value(item.get("provider"))
            model_id = _string_value(item.get("model_id"))
            if provider is None or model_id is None:
                continue
            loaded_records[(provider, model_id)] = _metadata_from_mapping(
                item, catalog_provider=provider
            )
        fetched_at = _parse_timestamp(document.get("fetched_at"))
        if fetched_at is None:
            return
        self._records = loaded_records
        self._source_version = _string_value(document.get("source_version"))
        self._fetched_at = fetched_at

    def _write_cache(self) -> None:
        if not self._persistence_enabled:
            return
        records = [
            {
                "provider": provider,
                "model_id": model_id,
                **metadata.as_dict(),
            }
            for (provider, model_id), metadata in sorted(self._records.items())
        ]
        document = {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "source": MODELS_DEV_API_URL,
            "source_version": self._source_version,
            "fetched_at": _format_timestamp(self._fetched_at or self._now()),
            "records": records,
        }
        content = (json.dumps(document, ensure_ascii=True, indent=2) + "\n").encode()
        try:
            if self._path.read_bytes() == content:
                return
        except OSError:
            pass

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._path.with_name(
                f".{self._path.name}.{uuid.uuid4().hex}.tmp"
            )
            try:
                temp_path.write_bytes(content)
                temp_path.replace(self._path)
            finally:
                temp_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(
                "Model metadata catalog cache write skipped: reason={}",
                type(exc).__name__,
            )

    def _enrich_info(
        self,
        provider_id: str,
        info: ProviderModelInfo,
    ) -> ProviderModelInfo:
        metadata = self._lookup(provider_id, info.model_id)
        if metadata is None:
            return info

        catalog_evidence = _capability_evidence_for_metadata(metadata)
        capability_evidence = _merge_capability_evidence(
            info.capability_evidence, catalog_evidence
        )
        reasoning = _merge_reasoning_evidence(info.reasoning, metadata)
        supports_vision = info.supports_vision
        if supports_vision is None:
            supports_vision = _vision_support_from_metadata(metadata)
        supports_thinking = info.supports_thinking
        if supports_thinking is None:
            supports_thinking = metadata.supports_reasoning
        return replace(
            info,
            supports_thinking=supports_thinking,
            supports_vision=supports_vision,
            reasoning=reasoning,
            capability_evidence=capability_evidence,
            catalog_metadata=metadata,
        )

    def _lookup(self, provider_id: str, model_id: str) -> ModelCatalogMetadata | None:
        for catalog_provider in _MODELS_DEV_PROVIDER_ALIASES.get(provider_id, ()):
            metadata = self._records.get((catalog_provider, model_id))
            if metadata is not None:
                return metadata
        return None


def _parse_models_dev_payload(
    payload: bytes,
    *,
    source_version: str,
    observed_at: str,
) -> dict[tuple[str, str], ModelCatalogMetadata]:
    document = json.loads(payload)
    if not isinstance(document, Mapping):
        raise ValueError("models.dev response was not an object")

    records: dict[tuple[str, str], ModelCatalogMetadata] = {}
    for provider, provider_value in document.items():
        if not isinstance(provider, str) or not isinstance(provider_value, Mapping):
            continue
        models = provider_value.get("models")
        if not isinstance(models, Mapping):
            continue
        for model_id, entry in models.items():
            if not isinstance(model_id, str) or not isinstance(entry, Mapping):
                continue
            records[(provider, model_id)] = _metadata_from_entry(
                provider,
                entry,
                source_version=source_version,
                observed_at=observed_at,
            )
    return records


def _metadata_from_entry(
    provider: str,
    entry: Mapping[str, Any],
    *,
    source_version: str,
    observed_at: str,
) -> ModelCatalogMetadata:
    modalities = entry.get("modalities")
    limits = entry.get("limit")
    modalities_mapping = modalities if isinstance(modalities, Mapping) else {}
    limits_mapping = limits if isinstance(limits, Mapping) else {}
    return ModelCatalogMetadata(
        display_name=_string_value(entry.get("name")),
        description=_string_value(entry.get("description")),
        family=_string_value(entry.get("family")),
        input_modalities=_string_tuple(modalities_mapping.get("input")),
        output_modalities=_string_tuple(modalities_mapping.get("output")),
        context_window=_positive_int(limits_mapping.get("context")),
        max_input_tokens=_positive_int(limits_mapping.get("input")),
        max_output_tokens=_positive_int(limits_mapping.get("output")),
        release_date=_string_value(entry.get("release_date")),
        last_updated=_string_value(entry.get("last_updated")),
        status=_string_value(entry.get("status")),
        open_weights=_bool_value(entry.get("open_weights")),
        supports_tools=_bool_value(entry.get("tool_call")),
        supports_structured_output=_bool_value(entry.get("structured_output")),
        supports_temperature=_bool_value(entry.get("temperature")),
        supports_reasoning=_bool_value(entry.get("reasoning")),
        catalog_provider=provider,
        source="models.dev",
        source_version=source_version,
        observed_at=observed_at,
    )


def _metadata_from_mapping(
    value: Mapping[str, Any],
    *,
    catalog_provider: str,
) -> ModelCatalogMetadata:
    return ModelCatalogMetadata(
        display_name=_string_value(value.get("display_name")),
        description=_string_value(value.get("description")),
        family=_string_value(value.get("family")),
        input_modalities=_string_tuple(value.get("input_modalities")),
        output_modalities=_string_tuple(value.get("output_modalities")),
        context_window=_positive_int(value.get("context_window")),
        max_input_tokens=_positive_int(value.get("max_input_tokens")),
        max_output_tokens=_positive_int(value.get("max_output_tokens")),
        release_date=_string_value(value.get("release_date")),
        last_updated=_string_value(value.get("last_updated")),
        status=_string_value(value.get("status")),
        open_weights=_bool_value(value.get("open_weights")),
        supports_tools=_bool_value(value.get("supports_tools")),
        supports_structured_output=_bool_value(value.get("supports_structured_output")),
        supports_temperature=_bool_value(value.get("supports_temperature")),
        supports_reasoning=_bool_value(value.get("supports_reasoning")),
        catalog_provider=catalog_provider,
        source=_string_value(value.get("source")) or "models.dev",
        source_version=_string_value(value.get("source_version")),
        observed_at=_string_value(value.get("observed_at")),
    )


def _capability_evidence_for_metadata(
    metadata: ModelCatalogMetadata,
) -> CapabilityEvidence:
    claims: dict[str, CapabilityEvidenceStatus] = {}
    modalities = {item.casefold() for item in metadata.input_modalities}
    output_modalities = {item.casefold() for item in metadata.output_modalities}
    if "text" in modalities:
        claims["text_input"] = CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED
    if "text" in output_modalities:
        claims["text_output"] = CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED
    if metadata.input_modalities:
        claims["vision_input"] = (
            CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED
            if "image" in modalities
            else CapabilityEvidenceStatus.UNSUPPORTED
        )
    if metadata.supports_tools is not None:
        claims["native_tools"] = _positive_claim(metadata.supports_tools)
    if metadata.supports_structured_output is not None:
        claims["structured_output"] = _positive_claim(
            metadata.supports_structured_output
        )
    if metadata.supports_reasoning is not None:
        claims["reasoning_effort"] = _positive_claim(metadata.supports_reasoning)
    return CapabilityEvidence(
        statuses=tuple(sorted(claims.items())),
        evidence_source="trusted_snapshot:models.dev",
        observed_at=metadata.observed_at,
        evidence_version=metadata.source_version,
        evidence_protocol="models.dev",
    )


def _merge_capability_evidence(
    provider_evidence: CapabilityEvidence,
    catalog_evidence: CapabilityEvidence,
) -> CapabilityEvidence:
    provider_claims = {
        capability: status
        for capability, status in provider_evidence.statuses
        if status is not CapabilityEvidenceStatus.UNKNOWN
    }
    catalog_claims = dict(catalog_evidence.statuses)
    merged_claims = {**catalog_claims, **provider_claims}
    if provider_claims:
        source = provider_evidence.evidence_source
        observed_at = provider_evidence.observed_at or catalog_evidence.observed_at
        version = (
            provider_evidence.evidence_version or catalog_evidence.evidence_version
        )
        protocol = (
            provider_evidence.evidence_protocol or catalog_evidence.evidence_protocol
        )
    elif catalog_claims:
        source = catalog_evidence.evidence_source
        observed_at = catalog_evidence.observed_at
        version = catalog_evidence.evidence_version
        protocol = catalog_evidence.evidence_protocol
    else:
        source = provider_evidence.evidence_source
        observed_at = provider_evidence.observed_at
        version = provider_evidence.evidence_version
        protocol = provider_evidence.evidence_protocol
    return CapabilityEvidence(
        statuses=tuple(sorted(merged_claims.items())),
        evidence_source=source,
        observed_at=observed_at,
        evidence_version=version,
        evidence_protocol=protocol,
    )


def _merge_reasoning_evidence(
    provider_evidence: ReasoningCapabilityEvidence,
    metadata: ModelCatalogMetadata,
) -> ReasoningCapabilityEvidence:
    if (
        provider_evidence.status is not ReasoningCapabilityStatus.UNKNOWN
        or metadata.supports_reasoning is None
    ):
        return provider_evidence
    status = (
        ReasoningCapabilityStatus.ACCEPTED_BUT_UNVERIFIED
        if metadata.supports_reasoning
        else ReasoningCapabilityStatus.UNSUPPORTED
    )
    return replace(
        provider_evidence,
        status=status,
        evidence_source="trusted_snapshot:models.dev",
        evidence_date=(
            provider_evidence.evidence_date
            or metadata.last_updated
            or metadata.release_date
        ),
        evidence_version=(
            provider_evidence.evidence_version or metadata.source_version
        ),
        evidence_protocol=provider_evidence.evidence_protocol or "models.dev",
    )


def _vision_support_from_metadata(metadata: ModelCatalogMetadata) -> bool | None:
    if not metadata.input_modalities:
        return None
    return "image" in {item.casefold() for item in metadata.input_modalities}


def _positive_claim(value: bool) -> CapabilityEvidenceStatus:
    return (
        CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED
        if value
        else CapabilityEvidenceStatus.UNSUPPORTED
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(
        dict.fromkeys(
            item.strip() for item in value if isinstance(item, str) and item.strip()
        )
    )


def _string_value(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _bool_value(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _positive_int(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else None
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


__all__ = ["MODELS_DEV_API_URL", "ModelMetadataCatalog"]
