# Capability snapshot upstream harvest

Issue: #47. This slice adds only a manual/build-time metadata adapter and precedence primitive. It does not add network polling, model routing, provider fallback, or a second catalog runtime.

## Current AgentSwitchboard baseline

Before this slice, AgentSwitchboard already had:

- first-class `supported | unsupported | unknown | accepted-but-unverified` capability states;
- provider model discovery and cache;
- explicit source/time/version/protocol provenance;
- conflict rejection inside one provider model-list payload;
- zero-network route diagnostics using cached evidence;
- fail-closed vision routing when support is unknown;
- registered browser/macOS/computer helper capabilities represented by implementation metadata rather than provider-name guesses.

The remaining #47 gap was the issue's lower-priority **trusted upstream snapshot** layer and an explicit reusable precedence rule across multiple evidence sources.

## LiteLLM public registry

- Repository: `BerriAI/litellm`
- Pin used for this harvest: `cdb60af0243d8c3aa3fe5531eb53b7364d4d5f27`
- License: MIT for content outside `enterprise/`; no enterprise code/data is used here.
- Relevant public files:
  - `model_prices_and_context_window.schema.json`
  - `model_prices_and_context_window.json`
  - `tests/test_litellm/test_muse_spark_1_2_model_metadata.py`

The schema explicitly treats capability booleans as optional catalog fields and says fields can be absent when unknown or false. AgentSwitchboard therefore does **not** treat a positive snapshot flag as live support proof. Positive public-catalog claims map to `accepted-but-unverified`; explicit `false` maps to `unsupported`; absent fields remain `unknown`.

Mapped fields:

- `supports_function_calling` -> `native_tools`
- `supports_parallel_function_calling` -> `parallel_tools`
- `supports_tool_choice` -> `named_tool_choice`
- `supports_response_schema` -> `structured_output`
- `supports_vision` / explicit image modality -> `vision_input`
- `supports_reasoning` -> `reasoning_effort`
- `max_input_tokens` -> trusted snapshot context ceiling
- `/v1/chat/completions`, `/v1/responses`, `/v1/messages` -> explicit protocol families

The current LiteLLM pinned fixture for `meta/muse-spark-1.2-contributor` is especially useful because it independently records a 1,048,576-token input window and explicit tool, parallel-tool, prompt-cache, reasoning, schema, tool-choice, vision, PDF and web-search support plus all three relevant API endpoints. AgentSwitchboard uses that as a deterministic fixture shape, not as permission to silently enable any paid route.

## CCR model catalog/discovery

- Repository: `musistudio/claude-code-router`
- Pin: `99f24806c6a2c660b16e53e95211c517448a6c90`
- License: MIT
- Relevant files:
  - `packages/core/src/agents/codex/model-catalog.ts`
  - `packages/core/src/gateway/features/model-discovery.ts`

CCR is useful as a design reference for composing explicitly configured per-model metadata with a catalog entry and exposing capabilities/context to clients. AgentSwitchboard does not import CCR's router, gateway, model-family heuristics, or permissive boolean fallback logic. Its stricter evidence states and provider-isolation policy remain authoritative.

## AgentSwitchboard precedence

From strongest to weakest:

1. `EXPLICIT_OVERRIDE` — operator/AgentSwitchboard override backed by a receipt;
2. `PROVIDER_DISCOVERY` — current provider model-list/discovery metadata;
3. `TRUSTED_UPSTREAM_SNAPSHOT` — manually pinned public catalog snapshot;
4. `MODEL_FAMILY_HINT` — narrowly maintained family hint, never provider-name inference;
5. `UNKNOWN`.

A weaker source cannot override a stronger source. Disagreements are preserved in the resolution receipt. Two equally authoritative sources that disagree fail closed instead of choosing the most permissive claim.

## Safety boundary

This module is deliberately not wired to auto-refresh or routing in the request hot path. Importing a newer upstream snapshot requires an explicit repository change and review. A snapshot cannot by itself authorize a paid provider/helper route; #22/#30 policy remains separate. Live/deterministic evidence can later promote `accepted-but-unverified` to `supported` without changing the public snapshot parser.
