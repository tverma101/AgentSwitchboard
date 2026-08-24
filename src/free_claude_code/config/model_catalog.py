"""Provider-independent visibility policy for discovered model catalogs.

Provider adapters may discover broadly.  This module owns the smaller client
visible catalog policy and deliberately has no provider-specific imports.
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

    Entries use fully-qualified ``provider/model`` refs.  ``*`` exposes every
    provider and ``provider/*`` exposes one provider.  Exact configured routes
    are handled separately by the model-list builders and remain routable.
    """

    mode: ModelCatalogMode = ModelCatalogMode.ALL
    allowlist: frozenset[str] = frozenset()

    def is_visible(self, provider_id: str, model_id: str) -> bool:
        """Return whether one discovered model is client-visible."""

        if self.mode is ModelCatalogMode.ALL:
            return True

        full_ref = normalize_model_ref(provider_id, model_id)
        return (
            "*" in self.allowlist
            or f"{provider_id}/*" in self.allowlist
            or full_ref in self.allowlist
        )


def parse_model_catalog_allowlist(value: str) -> frozenset[str]:
    """Parse comma/newline-separated exact refs and wildcards."""

    entries = value.replace("\r", "\n").replace("\n", ",").split(",")
    return frozenset(entry.strip() for entry in entries if entry.strip())


def normalize_model_ref(provider_id: str, model_id: str) -> str:
    """Return one fully-qualified ``provider/model`` reference.

    Discovery returns raw model ids while cached model metadata may already
    contain the provider prefix.  Normalize both forms before matching.
    """

    prefix = f"{provider_id}/"
    return model_id if model_id.startswith(prefix) else f"{prefix}{model_id}"
