"""Human-friendly model labels that never replace routable model ids."""

import re

from .provider_catalog import PROVIDER_CATALOG

_KNOWN_LABELS = {
    "deepseek-chat": "DeepSeek Chat",
    "deepseek-reasoner": "DeepSeek Reasoner",
    "deepseek-v4-flash-free": "DeepSeek V4 Flash Free",
    "deepseek-v4-flash": "DeepSeek V4 Flash",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
    "glm-5": "GLM 5",
    "glm-5.2": "GLM 5.2",
    "glm-5.1": "GLM 5.1",
}


def model_display_name(model_ref: str) -> str:
    """Return a readable label while preserving exact route identity.

    Aggregating providers commonly return nested ids such as
    ``openai/gpt-model``. The old labeler threw the namespace away and could
    render several distinct routes as the same ``GPT Model`` row. Keep the
    pretty leaf, but surface the nested provider/model suffix whenever dropping
    it would hide routing identity.
    """
    display_ref = model_ref.removeprefix("anthropic/")
    provider_id, separator, model_id = display_ref.partition("/")
    if not separator:
        return _pretty_model_id(model_ref)
    provider = PROVIDER_CATALOG.get(provider_id)
    provider_label = provider.display_name if provider is not None else provider_id
    friendly = f"{provider_label} · {_pretty_model_id(model_id)}"
    if "/" in model_id:
        return f"{friendly} [{model_id}]"
    return friendly


def disambiguate_model_labels(labels: dict[str, str]) -> dict[str, str]:
    """Make display labels collision-free using literal routable identities."""
    resolved = dict(labels)
    collisions: dict[str, list[str]] = {}
    for model_ref, label in labels.items():
        collisions.setdefault(label.casefold(), []).append(model_ref)

    for model_ref, label in labels.items():
        if len(collisions[label.casefold()]) <= 1:
            continue
        resolved[model_ref] = f"{label} [{model_ref}]"
    return resolved


def model_display_names(
    model_refs: list[str] | tuple[str, ...] | set[str],
) -> dict[str, str]:
    """Return readable, collision-free labels keyed by exact model refs."""
    refs = tuple(dict.fromkeys(model_refs))
    return disambiguate_model_labels(
        {model_ref: model_display_name(model_ref) for model_ref in refs}
    )


def _pretty_model_id(model_id: str) -> str:
    if model_id in _KNOWN_LABELS:
        return _KNOWN_LABELS[model_id]
    leaf = model_id.rsplit("/", 1)[-1]
    if leaf in _KNOWN_LABELS:
        return _KNOWN_LABELS[leaf]
    words = re.sub(r"[-_:]+", " ", leaf).split()
    return " ".join(
        word.upper() if word.isupper() else word.capitalize() for word in words
    )
