"""Stable logical model aliases above exact provider/model refs.

Aliases are intentionally thin: they do not perform provider discovery or
replace the routing engine.  They only let callers refer to a durable logical
name while Harness records/routes the exact provider model underneath.
"""

from dataclasses import dataclass


class ModelAliasError(ValueError):
    """Raised when alias configuration is malformed or cannot resolve."""


@dataclass(frozen=True, slots=True)
class ModelAliasMap:
    aliases: dict[str, str]

    def resolve(self, requested: str) -> str:
        """Resolve one logical alias, or return an exact provider ref unchanged."""

        if "/" in requested:
            return requested
        target = self.aliases.get(requested)
        if target is None:
            raise ModelAliasError(f"unknown model alias: {requested}")
        return target


def parse_model_aliases(value: str) -> ModelAliasMap:
    """Parse newline/comma separated ``alias=provider/model`` entries."""

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
        if "/" not in target:
            raise ModelAliasError(
                f"alias target must be an exact provider/model ref: {target}"
            )
        if alias in aliases:
            raise ModelAliasError(f"duplicate model alias: {alias}")
        aliases[alias] = target

    return ModelAliasMap(aliases)
