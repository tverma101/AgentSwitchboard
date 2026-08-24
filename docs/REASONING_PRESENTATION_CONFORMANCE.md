# Reasoning presentation conformance

## Purpose

Harness bridges providers whose reasoning semantics are not identical. In particular, OpenAI Responses reasoning items, provider-specific reasoning-token accounting, and Anthropic Messages `thinking` blocks must not be treated as interchangeable concepts.

This document defines the contract for issues #54, #55, and #56.

## Core invariant

The following facts are independent and must be represented independently:

1. reasoning was requested at some effort level;
2. the provider accepted the request;
3. the provider actually reported reasoning usage;
4. a reasoning item/id was emitted;
5. visible reasoning summary text was emitted;
6. reasoning text was emitted;
7. opaque/encrypted continuation state was emitted;
8. Harness emitted an Anthropic-compatible `thinking` block;
9. Claude Code displayed a thinking/reasoning UI surface;
10. the final answer text was emitted.

No implication between those states may be assumed without provider/client evidence.

## Semantic vocabulary

### Responses reasoning summary

A Responses `summary_text` value is a provider-returned summary of reasoning. Harness may present it through a Claude-compatible thinking surface only when that mapping is explicitly supported and tested. Internally it remains tagged as a summary, never as raw chain-of-thought.

### Responses reasoning text

Reasoning text, where a provider returns it, remains distinct from summary text. Do not collapse the two event families during streaming or aggregation.

### Opaque reasoning state

Reasoning ids, encrypted content, signatures, or equivalent continuation metadata are opaque. Preserve exact values when protocol continuity requires them, but do not parse, summarize, fabricate, or expose them as user-visible reasoning.

### Anthropic thinking block

A Claude `thinking` content block is a client-facing protocol object. Its visible text may itself be summarized or empty depending on the model/protocol behavior. The existence or absence of visible text does not prove whether the model reasoned internally.

## Muse Spark 1.2 contract

Muse Spark 1.2 Contributor is a Responses-routed OpenCode Go model. Harness currently sends named reasoning effort and requests automatic reasoning summaries where supported.

Before declaring reasoning presentation stable, collect live receipts for the supported effort matrix and record independently:

- requested effort;
- effective/accepted effort when observable;
- reasoning-token usage when reported;
- reasoning item/id presence;
- summary event presence and visible character count;
- reasoning-text event presence;
- opaque/encrypted state presence (hash/type only in receipts);
- Anthropic thinking events emitted by Harness;
- final text and terminal state;
- attempts and TTFT.

If Muse reasons but does not return a visible summary, Harness must not invent one.

## Claude Code without Anthropic spend

Claude Code client behavior can be black-box tested against an FCC-owned synthetic local gateway. This is the preferred way to determine how a specific installed Claude Code version renders and round-trips thinking without consuming Anthropic tokens.

Synthetic fixtures should cover:

- text only;
- visible thinking plus text;
- empty thinking plus opaque signature/state;
- redacted thinking;
- interleaved thinking and tool use;
- late signature delta;
- malformed/missing opaque state;
- thinking requested but text-only response;
- additive/unknown thinking event fields.

The gateway must record the next client request structurally so preservation, ordering, and omission can be proven rather than inferred from terminal appearance.

Synthetic client fixtures are evidence of Claude Code behavior only. They are not evidence of what Muse emits live.

## Presentation policy

Harness should prefer truthful absence over fabricated visibility:

- summary present -> may surface as a clearly typed thinking-summary presentation when client-compatible;
- opaque state only -> preserve continuity, no fabricated visible text;
- reasoning usage only -> record receipt, no fabricated thinking block;
- no reasoning evidence -> ordinary text/tool stream;
- unsupported conversion -> typed compatibility failure or explicit policy behavior.

Do not inject labels or explanatory text into prompts merely to make the UI look like Claude thinking. Presentation belongs at the protocol/UI boundary and must not destabilize cacheable prefixes.

## Tool continuation

Thinking/reasoning state associated with tool use must preserve ordering and identity across the entire tool loop. A provider stream may contain reasoning before a tool call, between calls, and after tool results. Conversion must not:

- move reasoning across tool boundaries;
- attach reasoning state to the wrong tool call;
- discard opaque continuation metadata required by the upstream model;
- fabricate Anthropic signatures;
- replay committed tool calls because a reasoning block could not be converted.

## Capability metadata

Reasoning support is not a boolean. Capability metadata should separately record:

- accepted effort values;
- default effort when known;
- reasoning-token accounting support;
- visible-summary support;
- opaque-continuation support;
- tool compatibility at relevant efforts;
- evidence source and provider/model/protocol version/date.

A request field being accepted is not proof that the provider used reasoning.

## Receipts and privacy

Receipts may contain:

- event type sequence;
- effort values;
- booleans for summary/reasoning/opaque-state presence;
- lengths;
- hashes of opaque metadata;
- token/cache counters;
- timing and attempt information.

Receipts must not contain raw private reasoning, prompts, final response text, opaque encrypted values, auth secrets, or tool payloads.

## Acceptance

Reasoning presentation is release-ready only when:

1. deterministic fixtures cover all visibility combinations;
2. Muse live receipts establish current provider behavior;
3. installed Claude Code behavior is proven with the zero-Anthropic synthetic harness;
4. summary, reasoning text, and opaque state remain distinct internally;
5. no visible thinking is fabricated when the upstream provides none;
6. tool continuation preserves required reasoning state and ordering;
7. #31 compatibility fingerprints detect client behavior changes across Claude Code updates;
8. #56 capability metadata exposes requested/effective reasoning behavior without hot-path discovery.
