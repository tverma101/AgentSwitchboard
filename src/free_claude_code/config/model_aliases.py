"""Stable logical model aliases above exact provider/model refs.

Aliases are a client-facing name layer. They never replace the exact provider
model ref used for routing, usage, or provider requests.
"""

from dataclasses import dataclass


class ModelAliasError(ValueError):
    """Raised when alias configuration is malformed or cannot resolve."""


def _is_reserved_claude_model_name(alias: str) -> bool:
    """Keep Claude compatibility ids owned by the gateway, not aliases."""

    return alias.casefold() == "claude" or alias.casefold().startswith("claude-")


@dataclass(frozen=True, slots=True)
class ModelAliasMap:
    """Validated logical names mapped to exact provider/model refs."""

    aliases: dict[str, str]

    def resolve(self, requested: str) -> str:
        """Resolve one alias, or return an exact provider ref unchanged."""

        if "/" in requested:
            return requested
        target = self.aliases.get(requested)
        if target is None:
            raise ModelAliasError(f"unknown model alias: {requested}")
        return target

    def resolve_if_configured(self, requested: str) -> str:
        """Resolve a configured alias while preserving ordinary Claude names."""

        if "/" in requested:
            return requested
        return self.aliases.get(requested, requested)


def parse_model_aliases(value: str) -> ModelAliasMap:
    """Parse newline/comma-separated ``alias=provider/model`` entries."""

    raw_entries = value.replace("\r", "\n").replace("\n", ",").split(",")
    aliases: dict[str, str] = {}

    for raw_entry in raw_entries:
        entry = raw_entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ModelAliasError(f"invalid alias entry: {entry}")
        alias, target = (part.strip() for part in entry.split("=", 1))
        if not alias or not target:
            raise ModelAliasError(f"invalid alias entry: {entry}")
        if "/" in alias:
            raise ModelAliasError(f"alias must not contain '/': {alias}")
        if _is_reserved_claude_model_name(alias):
            raise ModelAliasError(
                f"alias uses the reserved Claude model namespace: {alias}"
            )
        if "/" not in target:
            raise ModelAliasError(
                f"alias target must be an exact provider/model ref: {target}"
            )
        if alias in aliases:
            raise ModelAliasError(f"duplicate model alias: {alias}")
        aliases[alias] = target

    return ModelAliasMap(aliases)
