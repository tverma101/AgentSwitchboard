from free_claude_code.application.model_metadata import (
    CapabilityVerification,
    CapabilityVerificationStatus,
    ProviderModelInfo,
)
from free_claude_code.providers.runtime.model_cache import ProviderModelCache


def test_prefixed_model_cache_preserves_capability_verification() -> None:
    verification = CapabilityVerification(
        statuses=(("vision_input", CapabilityVerificationStatus.SKIPPED),),
        evidence_source="live_probe",
        observed_at="2026-08-24T20:00:00Z",
        evidence_version="probe-1",
        evidence_protocol="responses",
    )
    cache = ProviderModelCache()
    cache.cache_model_infos(
        "open_router",
        [
            ProviderModelInfo(
                "provider-model",
                capability_verification=verification,
            )
        ],
    )

    assert cache.cached_prefixed_model_infos() == (
        ProviderModelInfo(
            "open_router/provider-model",
            capability_verification=verification,
        ),
    )
