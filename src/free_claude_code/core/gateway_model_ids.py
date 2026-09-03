"""Gateway-safe model ID encoding shared by API and CLI adapters."""

from dataclasses import dataclass

GATEWAY_MODEL_ID_PREFIX = "anthropic"

# Per Claude Code's gateway protocol reference, gateway model ids are subject
# to two published client rules: ``/v1/models`` discovery keeps entries whose
# id contains ``claude`` or ``anthropic`` (case-insensitive), and model names
# the client does not recognize are treated as current models that receive
# ``thinking: {"type": "adaptive"}``. There is no ``claude-3-`` substring
# heuristic. Thinking is therefore controlled server-side: the prefixes below
# only select the FCC reasoning policy, and the Thinking indicator appears
# exactly when the provider stream carries thinking blocks back.
#
# Selecting ``claude-3-freecc-no-thinking/<provider>/<model>`` routes exactly
# like the underlying ref but resolves ``ReasoningPreference.OFF`` (upstream
# ``reasoning: {"effort": "none"}``, no thinking blocks emitted), while
# keeping the real provider/model ref reversible for routing.
NO_THINKING_GATEWAY_MODEL_ID_PREFIX = "claude-3-freecc-no-thinking"

# Symmetric opt-in for maximum FCC reasoning from inside Claude Code's own
# model picker. Selecting ``claude-3-freecc-ultra/<provider>/<model>`` routes
# exactly like the underlying ref but forces the ultracode preference
# (provider-neutral xhigh, upstream ``summary: "auto"``). Same reversibility
# contract as no-thinking.
#
# Note this is only the effort half of Claude Code's native ``ultracode``
# (``/effort ultracode`` sends xhigh *plus* client-side dynamic workflow
# orchestration). The orchestration half lives in the client and cannot be
# triggered by a model id; this row guarantees xhigh reasoning server-side
# even though gateway rows offer no client effort slider.
ULTRACODE_GATEWAY_MODEL_ID_PREFIX = "claude-3-freecc-ultra"


@dataclass(frozen=True, slots=True)
class DecodedGatewayModelId:
    provider_id: str
    provider_model: str
    force_reasoning_off: bool = False
    force_ultracode: bool = False


def gateway_model_id(provider_model_ref: str) -> str:
    """Return the normal Claude Code-discoverable id for a provider/model ref."""
    return f"{GATEWAY_MODEL_ID_PREFIX}/{provider_model_ref}"


def no_thinking_gateway_model_id(provider_model_ref: str) -> str:
    """Return a Claude Code-discoverable id that disables client thinking."""
    return f"{NO_THINKING_GATEWAY_MODEL_ID_PREFIX}/{provider_model_ref}"


def ultra_gateway_model_id(provider_model_ref: str) -> str:
    """Return a Claude Code-discoverable id that forces ultracode reasoning."""
    return f"{ULTRACODE_GATEWAY_MODEL_ID_PREFIX}/{provider_model_ref}"


def decode_gateway_model_id(model_name: str) -> DecodedGatewayModelId | None:
    """Decode a model id advertised by this gateway, if it is one."""
    prefix, separator, remainder = model_name.partition("/")
    if not separator:
        return None

    if prefix == GATEWAY_MODEL_ID_PREFIX:
        force_reasoning_off = False
        force_ultracode = False
    elif prefix == NO_THINKING_GATEWAY_MODEL_ID_PREFIX:
        force_reasoning_off = True
        force_ultracode = False
    elif prefix == ULTRACODE_GATEWAY_MODEL_ID_PREFIX:
        force_reasoning_off = False
        force_ultracode = True
    else:
        return None

    provider_id, provider_separator, provider_model = remainder.partition("/")
    if not provider_separator or not provider_model:
        return None

    return DecodedGatewayModelId(
        provider_id=provider_id,
        provider_model=provider_model,
        force_reasoning_off=force_reasoning_off,
        force_ultracode=force_ultracode,
    )
