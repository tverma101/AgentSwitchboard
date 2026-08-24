"""Terminal-only, zero-network route and capability diagnostics."""

import argparse
import json
from collections.abc import Sequence

from free_claude_code.application.capabilities import (
    Capability,
    CapabilityRoutingError,
    CapabilityRoutingMode,
)
from free_claude_code.application.route_diagnostics import (
    SYNTHETIC_REQUEST_SHAPES,
    build_route_diagnostic,
    parse_synthetic_shapes,
)
from free_claude_code.config.settings import Settings

_SHAPES = SYNTHETIC_REQUEST_SHAPES


def main(argv: Sequence[str] | None = None) -> None:
    """Print a metadata-only diagnostic and never contact a provider."""

    parser = _parser()
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command != "route":
        parser.error(f"unsupported command: {args.command}")
    try:
        payload = build_route_diagnostic(
            settings,
            model=args.model or settings.model,
            shapes=_parse_shapes(args.shape),
            mode=CapabilityRoutingMode(args.mode),
            known_capabilities=_parse_capabilities(args.known),
            supported_capabilities=_parse_capabilities(args.supported),
        )
    except (ValueError, CapabilityRoutingError) as exc:
        parser.error(str(exc))
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fcc-diagnose",
        description="Explain an FCC route using synthetic metadata only.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    route = subparsers.add_parser("route", help="diagnose a synthetic request shape")
    route.add_argument("--model", help="Claude or provider/model id to resolve")
    route.add_argument(
        "--shape",
        default="text",
        help="comma-separated synthetic shapes: " + ", ".join(sorted(_SHAPES)),
    )
    route.add_argument(
        "--mode",
        choices=[mode.value for mode in CapabilityRoutingMode],
        default=CapabilityRoutingMode.STRICT.value,
    )
    route.add_argument(
        "--known",
        default="",
        help="comma-separated capability evidence names known for the model",
    )
    route.add_argument(
        "--supported",
        default="",
        help="comma-separated capability evidence names supported by the model",
    )
    return parser


def _parse_shapes(value: str) -> tuple[str, ...]:
    return parse_synthetic_shapes(value)


def _parse_capabilities(value: str) -> frozenset[Capability]:
    capabilities: set[Capability] = set()
    unknown: list[str] = []
    for raw in value.split(","):
        name = raw.strip()
        if not name:
            continue
        try:
            capabilities.add(Capability(name))
        except ValueError:
            unknown.append(name)
    if unknown:
        raise ValueError(f"unknown capability name(s): {', '.join(sorted(unknown))}")
    return frozenset(capabilities)


__all__ = ["build_route_diagnostic", "main"]
