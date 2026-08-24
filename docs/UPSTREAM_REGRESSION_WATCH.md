# Upstream regression watch

This is a small, manually refreshed registry of upstream router failures that
map to a Harness protocol or client boundary. It is documentation and test
provenance only: Harness never polls these trackers on the request hot path.

The current entries were reviewed on 2026-08-24. External reports are treated
as failure-class references, not as fixtures to copy. Harness fixtures contain
synthetic values only and store no prompts, tool arguments, responses, images,
credentials, or provider bodies.

| Source | Failure class | Harness guard | Status |
| --- | --- | --- | --- |
| [CCR #1678](https://github.com/musistudio/claude-code-router/issues/1678) | Anthropic image silently dropped during an OpenAI conversion | `tests/core/openai_responses/test_provider_input.py` image conversion assertions and visual preflight tests | Current-source verified |
| [CCR #1643](https://github.com/musistudio/claude-code-router/issues/1643) | `tool_result` loses its call association on a Responses route | `tests/core/openai_responses/test_provider_input.py` tool-use/result round-trip assertions | Current-source verified |
| [CCR #1688](https://github.com/musistudio/claude-code-router/issues/1688) | Thinking history is rejected or discarded by a Responses upstream | reasoning and redacted-thinking assertions in `tests/core/openai_responses/` | Current-source verified |
| [Harness #49](https://github.com/tverma101/Harness/issues/49) | Responses cache/session affinity must remain metadata-only and must not destabilize the logical prefix | `test_responses_prompt_cache_key_*`, native Responses body tests, and request-shape/prefix hash tests | Current-source verified; native-vs-Harness cache benefit and parity remain unverified |
| [CCR #1697](https://github.com/musistudio/claude-code-router/issues/1697) | A `[1m]` virtual suffix leaks into a remapped upstream model id | `test_model_router_*virtual_context_suffix*` in `tests/application/test_routing.py` | Current-source verified; upstream context-header semantics remain separate |

## Refresh rule

On a manual refresh, add an entry only when the report maps to a supported
Harness boundary. Record the source URL, date, invariant, and the smallest
deterministic test or focused issue. Do not add an external issue merely
because it is interesting, and do not turn a skipped live probe into a passing
receipt.
