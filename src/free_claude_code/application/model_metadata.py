"""Application-owned model metadata."""

from dataclasses import dataclass, field, replace
from enum import StrEnum


class ReasoningCapabilityStatus(StrEnum):
    """Evidence state for one model's reasoning capability."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    ACCEPTED_BUT_UNVERIFIED = "accepted-but-unverified"
    SKIPPED = "skipped"


class CapabilityEvidenceStatus(StrEnum):
    """Evidence state for a general model capability."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    ACCEPTED_BUT_UNVERIFIED = "accepted-but-unverified"


class CapabilityVerificationStatus(StrEnum):
    """Outcome of an explicit capability verification run.

    Verification is deliberately separate from capability truth. In particular,
    a skipped or unverified live test is never evidence that a capability works.
    """

    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class CapabilityVerification:
    """Metadata-only result of an explicit capability verification run."""

    status: CapabilityVerificationStatus = CapabilityVerificationStatus.UNVERIFIED
    evidence_source: str = "unknown"
    observed_at: str | None = None
    evidence_version: str | None = None
    evidence_protocol: str | None = None

    @property
    def is_positive_evidence(self) -> bool:
        """Return whether this run positively verified the capability path."""

        return self.status is CapabilityVerificationStatus.PASS

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe diagnostic representation."""

        return {
            "status": self.status.value,
            "positive_evidence": self.is_positive_evidence,
            "evidence_source": self.evidence_source,
            "observed_at": self.observed_at,
            "evidence_version": self.evidence_version,
            "evidence_protocol": self.evidence_protocol,
        }


@dataclass(frozen=True, slots=True)
class CapabilityEvidence:
    """Metadata-only capability claims and their provenance."""

    statuses: tuple[tuple[str, CapabilityEvidenceStatus], ...] = ()
    evidence_source: str = "unknown"
    observed_at: str | None = None
    evidence_version: str | None = None
    evidence_protocol: str | None = None

    def status_for(self, capability: str) -> CapabilityEvidenceStatus:
        """Return the recorded status for a capability, or unknown."""

        for name, status in self.statuses:
            if name == capability:
                return status
        return CapabilityEvidenceStatus.UNKNOWN

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe diagnostic representation."""

        return {
            "statuses": {
                capability: status.value for capability, status in self.statuses
            },
            "evidence_source": self.evidence_source,
            "observed_at": self.observed_at,
            "evidence_version": self.evidence_version,
            "evidence_protocol": self.evidence_protocol,
        }

    def with_observed_at(self, observed_at: str) -> CapabilityEvidence:
        """Stamp a provider-observation time without replacing source claims."""

        if self.observed_at is not None:
            return self
        return replace(self, observed_at=observed_at)


@dataclass(frozen=True, slots=True)
class ReasoningCapabilityEvidence:
    """Explicit reasoning evidence, kept separate from legacy booleans.

    A provider accepting a request field is represented as
    ``accepted-but-unverified``. It is never promoted to ``supported`` without
    deterministic or live evidence that the model actually emitted reasoning.
    """

    status: ReasoningCapabilityStatus = ReasoningCapabilityStatus.UNKNOWN
    effort_evidence: tuple[tuple[str, ReasoningCapabilityStatus], ...] = ()
    provider_default_effort: str | None = None
    reports_reasoning_tokens: bool | None = None
    emits_visible_summary: bool | None = None
    emits_opaque_continuation: bool | None = None
    tool_compatible_efforts: tuple[str, ...] = ()
    evidence_source: str = "unknown"
    evidence_date: str | None = None
    evidence_version: str | None = None
    evidence_protocol: str | None = None

    def status_for_effort(self, effort: str) -> ReasoningCapabilityStatus:
        """Return the recorded status for an effort, or unknown if absent."""

        for name, status in self.effort_evidence:
            if name == effort:
                return status
        return ReasoningCapabilityStatus.UNKNOWN

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe diagnostic representation."""

        return {
            "status": self.status.value,
            "effort_evidence": {
                effort: status.value for effort, status in self.effort_evidence
            },
            "provider_default_effort": self.provider_default_effort,
            "reports_reasoning_tokens": self.reports_reasoning_tokens,
            "emits_visible_summary": self.emits_visible_summary,
            "emits_opaque_continuation": self.emits_opaque_continuation,
            "tool_compatible_efforts": list(self.tool_compatible_efforts),
            "evidence_source": self.evidence_source,
            "evidence_date": self.evidence_date,
            "evidence_version": self.evidence_version,
            "evidence_protocol": self.evidence_protocol,
        }


@dataclass(frozen=True, slots=True)
class ProviderModelInfo:
    """Provider model metadata used to shape the application model catalog."""

    model_id: str
    supports_thinking: bool | None = None
    supports_vision: bool | None = None
    accepted_image_types: tuple[str, ...] = ()
    reasoning: ReasoningCapabilityEvidence = field(
        default_factory=ReasoningCapabilityEvidence
    )
    capability_evidence: CapabilityEvidence = field(default_factory=CapabilityEvidence)
    capability_verification: CapabilityVerification = field(
        default_factory=CapabilityVerification
    )

    def with_observed_at(self, observed_at: str) -> ProviderModelInfo:
        """Stamp the catalog observation time on general capability evidence."""

        return replace(
            self,
            capability_evidence=self.capability_evidence.with_observed_at(observed_at),
        )


@dataclass(frozen=True, slots=True)
class ProviderModelRefreshResult:
    """Per-provider outcome of one model-catalog refresh."""

    refreshed_provider_ids: tuple[str, ...] = ()
    failed_provider_ids: tuple[str, ...] = ()
