"""Terminal-only, zero-network route and capability diagnostics."""

import argparse
import json
from collections.abc import Sequence
from typing import Any

from free_claude_code.application.capabilities import (
    Capability,
    CapabilityRouter,
    CapabilityRoutingError,
    CapabilityRoutingMode,
    CapabilityRoutingPolicy,
    required_capabilities_for_messages,
)
from free_claude_code.application.routing import ModelRouter
from free_claude_code.config.settings import Settings
from free_claude_code.core.anthropic.models import Message, MessagesRequest, Tool
from free_claude_code.providers.opencode_go import protocol_for_model

_SHAPES = frozenset(
    {
        "text",
        "tools",
        "parallel-tools",
        "vision",
        "image-tool-result",
        "reasoning",
        "structured",
        "browser",
        "macos",
        "screenshot",
    }
)


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


def build_route_diagnostic(
    settings: Settings,
    *,
    model: str | None = None,
    shapes: Sequence[str] = ("text",),
    mode: CapabilityRoutingMode = CapabilityRoutingMode.STRICT,
    known_capabilities: frozenset[Capability] = frozenset(),
    supported_capabilities: frozenset[Capability] = frozenset(),
) -> dict[str, Any]:
    """Build one synthetic route explanation without provider I/O."""

    requested_model = model or settings.model
    request = _synthetic_request(requested_model, shapes)
    resolved = ModelRouter(settings).resolve(request.model)
    required = required_capabilities_for_messages(request)
    policy = CapabilityRoutingPolicy(mode=mode)
    router = CapabilityRouter(policy)
    error: str | None = None
    try:
        plan = router.plan(
            required,
            controller_provider=resolved.provider_id,
            controller_model=resolved.provider_model,
            supported_capabilities=supported_capabilities,
            known_capabilities=known_capabilities,
        )
    except CapabilityRoutingError as exc:
        error = str(exc)
        plan = None

    return {
        "diagnostic": "capability_route",
        "network": "none",
        "billable_requests": 0,
        "controller": {
            "requested_model": requested_model,
            "provider": resolved.provider_id,
            "model": resolved.provider_model,
            "model_ref": resolved.provider_model_ref,
            "protocol": _protocol_name(resolved.provider_id, resolved.provider_model),
            "virtual_context_window": resolved.virtual_context_window,
        },
        "request_shape": list(shapes),
        "required": required.as_dict(),
        "capability_evidence": _capability_evidence(
            required.capabilities,
            known=known_capabilities,
            supported=supported_capabilities,
        ),
        "policy": {
            "mode": mode.value,
            "controller_failover": False,
            "allowed_helpers": [],
        },
        "decision": (
            plan.as_receipt()
            if plan is not None
            else {
                "controller_provider": resolved.provider_id,
                "controller_model": resolved.provider_model,
                "required": required.as_dict(),
                "mode": mode.value,
                "decision": "rejected",
                "error": error,
            }
        ),
    }


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
    shapes = tuple(
        dict.fromkeys(part.strip() for part in value.split(",") if part.strip())
    )
    unknown = sorted(set(shapes) - _SHAPES)
    if unknown:
        raise ValueError(f"unknown synthetic request shape(s): {', '.join(unknown)}")
    return shapes or ("text",)


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


def _synthetic_request(model: str, shapes: Sequence[str]) -> MessagesRequest:
    shape_set = set(shapes)
    tools: list[Tool] = []
    if shape_set & {
        "tools",
        "parallel-tools",
        "browser",
        "macos",
        "screenshot",
    }:
        tool_name = "lookup"
        if "browser" in shape_set:
            tool_name = "browser_navigate"
        elif "macos" in shape_set:
            tool_name = "macos_click"
        elif "screenshot" in shape_set:
            tool_name = "screenshot"
        tools.append(
            Tool(
                name=tool_name,
                description="synthetic diagnostic tool",
                input_schema={"type": "object", "properties": {}},
            )
        )
        if "parallel-tools" in shape_set:
            tools.append(
                Tool(
                    name="lookup_second",
                    description="synthetic diagnostic tool",
                    input_schema={"type": "object", "properties": {}},
                )
            )

    content: str | list[dict[str, Any]] = "synthetic diagnostic request"
    if "vision" in shape_set:
        content = [
            {"type": "text", "text": "synthetic image request"},
            {
                "type": "image",
                "source": {"type": "url", "url": "https://example.invalid/image"},
            },
        ]
    if "image-tool-result" in shape_set:
        content = [
            {
                "type": "tool_result",
                "tool_use_id": "synthetic_tool",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": "https://example.invalid/screenshot",
                        },
                    }
                ],
            }
        ]
    request_data: dict[str, Any] = {
        "model": model,
        "messages": [Message(role="user", content=content)],
        "tools": tools or None,
        "thinking": {"enabled": True} if "reasoning" in shape_set else None,
        "output_config": {"format": {"type": "json_schema"}}
        if "structured" in shape_set
        else None,
    }
    if "parallel-tools" in shape_set:
        request_data["parallel_tool_calls"] = True
    return MessagesRequest.model_validate(request_data)


def _capability_evidence(
    required: frozenset[Capability],
    *,
    known: frozenset[Capability],
    supported: frozenset[Capability],
) -> list[dict[str, str]]:
    baseline = {Capability.TEXT_INPUT, Capability.TEXT_OUTPUT}
    rows: list[dict[str, str]] = []
    for capability in sorted(required, key=lambda item: item.value):
        if capability in baseline or capability in supported:
            state = "supported"
        elif capability in known:
            state = "unsupported"
        else:
            state = "unknown"
        rows.append(
            {
                "capability": capability.value,
                "state": state,
                "evidence_source": (
                    "protocol-baseline" if capability in baseline else "cli-asserted"
                ),
            }
        )
    return rows


def _protocol_name(provider_id: str, model: str) -> str:
    if provider_id != "opencode_go":
        return "provider-defined"
    try:
        return protocol_for_model(model).value
    except Exception:
        return "unknown"


__all__ = ["build_route_diagnostic", "main"]
