"""Provider-prefixed model reference helpers."""

import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ConfiguredChatModelRef:
    """A unique configured chat model reference."""

    model_ref: str
    provider_id: str
    model_id: str


@dataclass(frozen=True, slots=True)
class NormalizedModelRef:
    """Canonical model ref plus a client-only virtual context directive."""

    model_ref: str
    virtual_context_window: int | None = None


_VIRTUAL_CONTEXT_SUFFIX = re.compile(
    r"^(?P<model>.+)\[(?P<amount>[0-9]+)(?P<unit>[kKmM])\]$"
)


def normalize_model_ref(model_ref: str) -> NormalizedModelRef:
    """Remove a Claude virtual context suffix before provider lookup.

    Claude Code can attach a suffix such as ``[1m]`` to a model selected for a
    child session.  That suffix is a client capability directive, not part of
    the provider model id.  Keep the parsed window in routing metadata so a
    later client-policy layer can honor it, but never leak it to an upstream
    provider that does not advertise the virtual syntax.
    """

    normalized = model_ref.strip()
    match = _VIRTUAL_CONTEXT_SUFFIX.fullmatch(normalized)
    if match is None:
        return NormalizedModelRef(model_ref=normalized)
    amount = int(match.group("amount"))
    multiplier = 1_000 if match.group("unit").casefold() == "k" else 1_000_000
    return NormalizedModelRef(
        model_ref=match.group("model"),
        virtual_context_window=amount * multiplier,
    )


class ChatModelConfig(Protocol):
    model: str
    model_fable: str | None
    model_opus: str | None
    model_sonnet: str | None
    model_haiku: str | None


def parse_provider_type(model_ref: str) -> str:
    """Extract provider type from any 'provider/model' string."""

    return model_ref.split("/", 1)[0]


def parse_model_name(model_ref: str) -> str:
    """Extract model name from any 'provider/model' string."""

    return model_ref.split("/", 1)[1]


def configured_chat_model_refs(
    settings: ChatModelConfig,
) -> tuple[ConfiguredChatModelRef, ...]:
    """Return unique configured chat provider/model refs."""

    model_refs = dict.fromkeys(
        model_ref
        for model_ref in (
            settings.model,
            settings.model_fable,
            settings.model_opus,
            settings.model_sonnet,
            settings.model_haiku,
        )
        if model_ref is not None
    )

    return tuple(
        ConfiguredChatModelRef(
            model_ref=model_ref,
            provider_id=parse_provider_type(model_ref),
            model_id=parse_model_name(model_ref),
        )
        for model_ref in model_refs
    )
