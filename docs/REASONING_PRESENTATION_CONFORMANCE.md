# Reasoning presentation conformance

> **Status: partially shipped.** Current `main` has live Muse effort receipts for
> low/medium/high/xhigh/max, preserves requested/effective effort separately,
> and has direct `off`/`minimal` boundary evidence with opaque reasoning hidden
> from the Anthropic stream. Remaining work is chiefly zero-Anthropic synthetic
> Claude UX conformance and deeper exact-shape/continuation coverage (#54-#56).

AgentSwitchboard bridges providers whose reasoning semantics are not identical. Responses
reasoning items, reasoning-token accounting, visible summaries, opaque
continuation state, Anthropic `thinking` blocks, Claude UI presentation, and
final text are separate facts and must remain separately represented.

## Core invariants

Never infer that reasoning usage implies visible reasoning, that opaque state is
human-readable, or that an Anthropic thinking block proves raw chain-of-thought
was returned. If a provider emits opaque state only, preserve it only when
required for continuation and do not fabricate visible text.

Responses summaries may arrive as incremental deltas, completed text events,
summary-part events, or a final reasoning item snapshot. The adapter must
normalize those shapes by item and part identity, reconcile final snapshots
without duplicate emission, and preserve a non-empty final summary rather than
treating the stream as empty. Opaque-only reasoning remains redacted.

## Muse contract

For each supported effort record requested/effective effort, reasoning-token
usage, reasoning item/id presence, visible summary presence/length, reasoning
text presence, opaque-state presence by type/hash only, Anthropic thinking-event
shape, final terminal state, attempts, and timing.

Muse's highest accepted wire effort may differ from the client-facing label;
receipts must preserve both rather than pretending they are identical.

## Synthetic Claude client fixtures

A local FCC-owned synthetic gateway should black-box test the literal Claude
client without Anthropic spend. Cover text-only, visible thinking + text, empty
thinking + opaque state, redacted thinking, thinking interleaved with tools,
late signature state, malformed/missing opaque state, requested-thinking but
text-only output, and safe additive fields.

The next client request should be captured structurally so ordering and
continuation can be proven rather than inferred from terminal appearance.
Synthetic tests prove Claude behavior only; they do not prove live Muse output.

## Presentation policy

- visible provider summary -> may surface only through an explicitly supported
  summary presentation;
- opaque state only -> preserve continuity, no fabricated visible text;
- reasoning usage only -> receipt only, no invented thinking content;
- no reasoning evidence -> ordinary text/tool stream;
- unsupported conversion -> explicit compatibility behavior or failure.

Reasoning state around tool use must retain order and identity. Conversion must
not move state across tool boundaries, attach it to the wrong call, fabricate
signatures, discard required continuation metadata, or replay committed tools.

## Capability metadata

Reasoning support is not one boolean. Track accepted efforts, default/effective
effort where known, reasoning-token accounting, visible-summary support,
opaque-continuation support, tool compatibility, and evidence source/date.

## Receipt privacy

Receipts may contain event sequences, effort values, booleans, lengths, opaque
metadata hashes, token/cache counters, timing, and attempts. Do not commit raw
private reasoning, prompts, response text, encrypted values, secrets, or tool
payloads.

## Remaining acceptance

Reasoning presentation is fully certified only when deterministic visibility
fixtures, current Muse receipts, literal-Claude synthetic UX tests, exact state
separation, tool continuation, compatibility fingerprinting, and capability
metadata all agree.
