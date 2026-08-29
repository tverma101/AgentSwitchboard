# Upstream regression watch

This is a small, manually refreshed registry of upstream router failures that
map to an AgentSwitchboard protocol or client boundary. It is documentation and test
provenance only: AgentSwitchboard never polls these trackers on the request hot path.

The current entries were re-verified against the upstream issue bodies on
2026-08-26. External reports are treated as failure-class references, not as
fixtures to copy. AgentSwitchboard fixtures contain synthetic values only and store no
prompts, tool arguments, responses, images, credentials, or provider bodies.

## Promoted regressions

| Source | Upstream failure class | AgentSwitchboard invariant / deterministic owner | Status |
| --- | --- | --- | --- |
| [CCR #1678](https://github.com/musistudio/claude-code-router/issues/1678), 2026-08-16 | Anthropic image blocks are silently dropped during Anthropic -> OpenAI conversion | `tests/core/openai_responses/test_provider_input.py::test_build_responses_provider_request_preserves_multiturn_protocol` proves a synthetic base64 image becomes `input_image`, and `::test_build_responses_provider_request_preserves_image_inside_tool_result` proves a Computer Use image remains an `input_image` inside `function_call_output.output`; unsupported nested shapes still fail loudly rather than dropping media | Covered on `main` |
| [CCR #1643](https://github.com/musistudio/claude-code-router/issues/1643), 2026-08-08 | Anthropic `tool_result.tool_use_id` loses association with the prior Responses call | `tests/core/openai_responses/test_provider_input.py::test_build_responses_provider_request_preserves_multiturn_protocol` proves `tool_use` -> `function_call.call_id` and matching `tool_result` -> `function_call_output.call_id` survive together | Covered on `main` |
| [CCR #1686](https://github.com/musistudio/claude-code-router/issues/1686), 2026-08-17 | Thinking blocks in Anthropic history break an OpenAI Responses route | `tests/core/openai_responses/test_provider_input.py::test_build_responses_provider_request_preserves_multiturn_protocol` converts synthetic thinking/redacted-thinking history into a Responses reasoning item while preserving the following text/tool state; client-only controls are separately rejected or consumed explicitly | Covered structurally on `main`; provider-specific live acceptance remains evidence work |
| [CCR #1688](https://github.com/musistudio/claude-code-router/issues/1688), 2026-08-18 | Session affinity is missing from a body-only Responses hop, breaking encrypted continuation/cache locality | `tests/core/openai_responses/test_prompt_cache_key_invariants.py` plus the `test_responses_prompt_cache_key_*` cases in `test_provider_input.py` prove explicit-key precedence, Claude-session fallback, metadata fallback, unsafe-key rejection, and turn-stable cache identity | Covered on `main`; live cache economics remain #17 |
| [CCR #1693](https://github.com/musistudio/claude-code-router/issues/1693), 2026-08-19 | A remapped `[1m]` virtual suffix leaks into the provider model id and causes upstream 404s | `tests/application/test_routing.py::test_model_router_strips_virtual_context_suffix_before_provider_dispatch` and `::test_model_router_normalizes_alias_target_virtual_context_suffix` prove canonicalization happens before provider dispatch | Covered on `main` |
| [CCR #1615](https://github.com/musistudio/claude-code-router/issues/1615), 2026-07-31 | Cross-protocol fallback retries a body without re-translating it for the new protocol | #42 owns the typed retry/fallback matrix and must prohibit replaying a provider-shaped body across incompatible protocols | Tracked by focused issue #42; controller failover remains off by default |
| [CCR #1697](https://github.com/musistudio/claude-code-router/issues/1697), 2026-08-19 | Provider-specific request/header transforms are lost when a later fallback target is selected | #42 owns fallback-target construction; any explicitly allowed target must build its request from canonical controller input plus that target's provider policy rather than reuse a prior target's transformed request | Tracked by focused issue #42; controller failover remains off by default |

## Corrections from the 2026-08-26 refresh

The earlier registry accidentally associated the wrong failure descriptions with
CCR #1688, #1693, and #1697. The issue bodies were reopened and the mapping
above now uses the actual upstream reports. The thinking-history report is
CCR #1686, prompt-cache/session affinity is #1688, and virtual-suffix subagent
normalization is #1693. CCR #1697 is instead a provider-transform/fallback
failure and therefore belongs to #42.

This is exactly why the registry records URLs and deterministic owners instead
of treating issue numbers as permanent shorthand for an assumed bug class.

## Refresh rule

On a manual refresh, add an entry only when the report maps to a supported
AgentSwitchboard boundary. Record the source URL/date, invariant, and the smallest
deterministic test or focused issue. Do not add an external issue merely
because it is interesting, and do not turn a skipped live probe into a passing
receipt.

A quarterly/manual refresh is sufficient until automation demonstrates value.
No watch or discovery work belongs on the request hot path.
