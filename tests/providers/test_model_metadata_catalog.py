import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from free_claude_code.application.model_metadata import (
    CapabilityEvidenceStatus,
    ProviderModelInfo,
    ReasoningCapabilityStatus,
)
from free_claude_code.providers.runtime.model_metadata_catalog import (
    ModelMetadataCatalog,
)


def _models_dev_payload() -> bytes:
    return json.dumps(
        {
            "opencode": {
                "models": {
                    "mimo-v2.5-free": {
                        "name": "MiMo V2.5 Free",
                        "description": "MiMo omni model for text, image, video, audio, and agents",
                        "family": "mimo-v2.5-free",
                        "reasoning": True,
                        "tool_call": True,
                        "structured_output": True,
                        "temperature": True,
                        "release_date": "2026-04-24",
                        "last_updated": "2026-04-24",
                        "modalities": {
                            "input": ["text", "image", "audio", "video"],
                            "output": ["text"],
                        },
                        "limit": {
                            "context": 200000,
                            "input": 168000,
                            "output": 32000,
                        },
                    }
                }
            },
            "openrouter": {
                "models": {
                    "text-only": {
                        "name": "Text Only",
                        "modalities": {"input": ["text"], "output": ["text"]},
                        "limit": {"context": 32768, "output": 4096},
                    }
                }
            },
        }
    ).encode()


@pytest.mark.asyncio
async def test_catalog_enriches_all_provider_models_with_one_fetch(
    tmp_path: Path,
) -> None:
    calls = 0

    async def fetch_payload() -> bytes:
        nonlocal calls
        calls += 1
        return _models_dev_payload()

    now = datetime(2026, 8, 27, 20, 0, tzinfo=UTC)
    catalog = ModelMetadataCatalog(
        tmp_path / "model-metadata-catalog.json",
        fetch_payload=fetch_payload,
        now=lambda: now,
    )

    enriched = await catalog.enrich_model_infos(
        {
            "opencode_zen": {ProviderModelInfo("mimo-v2.5-free")},
            "open_router": {ProviderModelInfo("text-only")},
        }
    )

    assert calls == 1
    mimo = next(iter(enriched["opencode_zen"]))
    assert mimo.supports_vision is True
    assert mimo.supports_thinking is True
    assert mimo.reasoning.status is ReasoningCapabilityStatus.ACCEPTED_BUT_UNVERIFIED
    assert mimo.capability_evidence.status_for("vision_input") is (
        CapabilityEvidenceStatus.ACCEPTED_BUT_UNVERIFIED
    )
    assert mimo.catalog_metadata is not None
    assert mimo.catalog_metadata.display_name == "MiMo V2.5 Free"
    assert mimo.catalog_metadata.input_modalities == (
        "text",
        "image",
        "audio",
        "video",
    )
    assert mimo.catalog_metadata.context_window == 200000
    assert mimo.catalog_metadata.max_output_tokens == 32000
    assert mimo.catalog_metadata.source == "models.dev"

    text_only = next(iter(enriched["open_router"]))
    assert text_only.supports_vision is False
    assert text_only.capability_evidence.status_for("vision_input") is (
        CapabilityEvidenceStatus.UNSUPPORTED
    )

    await catalog.enrich_model_infos(
        {"opencode_zen": {ProviderModelInfo("mimo-v2.5-free")}}
    )
    assert calls == 1

    persisted = json.loads(
        (tmp_path / "model-metadata-catalog.json").read_text(encoding="utf-8")
    )
    assert persisted["schema_version"] == 1
    assert persisted["source_version"]
    assert len(persisted["records"]) == 2


@pytest.mark.asyncio
async def test_catalog_reuses_fresh_persisted_snapshot_without_fetch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "model-metadata-catalog.json"
    now = datetime(2026, 8, 27, 20, 0, tzinfo=UTC)
    calls = 0

    async def fetch_payload() -> bytes:
        nonlocal calls
        calls += 1
        return _models_dev_payload()

    first = ModelMetadataCatalog(path, fetch_payload=fetch_payload, now=lambda: now)
    await first.enrich_model_infos(
        {"opencode_zen": {ProviderModelInfo("mimo-v2.5-free")}}
    )
    assert calls == 1

    async def unexpected_fetch() -> bytes:
        raise AssertionError("fresh persisted catalog should not fetch")

    second = ModelMetadataCatalog(
        path,
        fetch_payload=unexpected_fetch,
        now=lambda: now + timedelta(hours=1),
    )
    info = next(
        iter(
            (
                await second.enrich_model_infos(
                    {"opencode_zen": {ProviderModelInfo("mimo-v2.5-free")}}
                )
            )["opencode_zen"]
        )
    )
    assert info.supports_vision is True
    assert info.catalog_metadata is not None


@pytest.mark.asyncio
async def test_catalog_failure_preserves_provider_metadata_and_is_cooled_down(
    tmp_path: Path,
) -> None:
    calls = 0

    async def fetch_payload() -> bytes:
        nonlocal calls
        calls += 1
        raise OSError("catalog unavailable")

    catalog = ModelMetadataCatalog(
        tmp_path / "model-metadata-catalog.json",
        fetch_payload=fetch_payload,
        now=lambda: datetime(2026, 8, 27, 20, 0, tzinfo=UTC),
    )
    original = ProviderModelInfo("mimo-v2.5-free", supports_vision=True)

    first = await catalog.enrich_model_infos({"opencode_zen": {original}})
    second = await catalog.enrich_model_infos({"opencode_zen": {original}})

    assert calls == 1
    assert first["opencode_zen"] == frozenset({original})
    assert second["opencode_zen"] == frozenset({original})


@pytest.mark.asyncio
async def test_local_provider_does_not_trigger_public_catalog_fetch(
    tmp_path: Path,
) -> None:
    async def unexpected_fetch() -> bytes:
        raise AssertionError("local provider should not fetch models.dev")

    catalog = ModelMetadataCatalog(
        tmp_path / "model-metadata-catalog.json",
        fetch_payload=unexpected_fetch,
    )
    original = ProviderModelInfo("local-model")

    result = await catalog.enrich_model_infos({"lmstudio": {original}})

    assert result == {"lmstudio": frozenset({original})}
