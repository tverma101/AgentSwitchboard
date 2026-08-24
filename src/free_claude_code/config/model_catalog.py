"""Provider-independent visibility policy for discovered model catalogs.

This module intentionally contains no provider-specific behavior.  Provider
adapters may discover as many models as they need; clients should only see the
subset selected by a catalog policy.
"""

from dataclasses import dataclass
from enum import StrEnum


class ModelCatalogMode(StrEnum):
    """How discovered provider models are exposed to clients."""

    ALL = "all"
    CURATED = "curated"


@dataclass(frozen=True, slots=True)
class ModelCatalogPolicy:
    """Normalized model-catalog visibility policy.

    Entries use fully-qualified model refs (``provider/model``).  ``*`` exposes
    all discovery and ``provider/*`` exposes one provider.  Exact configured
    routing remains a separate concern; hiding discovery must never make an
    explicit MODEL route invalid.
    """

    mode: ModelCatalogMode = ModelCatalogMode.ALL
    allowlist: frozenset[str] = frozenset()

    def is_visible(self, provider_id: str, model_id: str) -> bool:
        if self.mode is ModelCatalogMode.ALL:
            return True

        full_ref = normalize_model_ref(provider_id, model_id)
        return (
            "*" in self.allowlist
            or f"{provider_id}/*" in self.allowlist
            or full_ref in self.allowlist
        )


def parse_model_catalog_allowlist(value: str) -> frozenset[str]:
    """Parse comma/newline-separated exact refs and wildcards.

    Empty entries are ignored.  Whitespace is stripped.  Validation of whether
    a provider/model actually exists belongs to discovery/routing, not here, so
    custom model refs remain representable.
    """

    entries = value.replace("\r", "\n").replace("\n", ",").split(",")
    return frozenset(entry.strip() for entry in entries if entry.strip())


def normalize_model_ref(provider_id: str, model_id: str) -> str:
    """Return one fully-qualified ``provider/model`` reference.

    Provider discovery normally reports an unprefixed model id, while cached
    metadata may already contain the provider prefix.  Normalize both forms so
    policy matching is deterministic.
    """

    prefix = f"{provider_id}/"
    return model_id if model_id.startswith(prefix) else f"{prefix}{model_id}"
