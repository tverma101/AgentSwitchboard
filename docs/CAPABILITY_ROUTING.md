# Capability-aware routing

> **Status: active design contract, not a shipped-feature claim.** Current `main`
> already has explicit provider/model routing, model capability metadata,
> provider-isolation primitives, stable aliases/catalog visibility, and an
> opt-in loopback CDP helper. Full request-derived capability routing and
> controller/helper orchestration described below remain planned work tracked
> by #30 and the linked capability issues.

Tracks #30. This document defines the runtime contract for capability-aware
routing. It intentionally does not change production routing by itself.

## Why this exists

A Claude-facing model name can resolve to one configured provider/model and
reasoning policy, but that is insufficient once a request requires a capability
the selected controller model does not have.

Examples:

- a blind controller receives an image attachment;
- computer use can be solved semantically through DOM/AX without pixels;
- a request asks for named tool choice but the upstream supports only `auto`;
- a screenshot needs a vision helper while the original controller stays in
  charge;
- a helper is available but belongs to a provider the session is not allowed to
  bill.

Capability routing must make those decisions explicitly and before upstream
spend.

## Required capability set

Derive a deterministic `RequiredCapabilitySet` from the request and requested
tool workflow. Initial vocabulary should include:

- text input/output
- native tools
- parallel tools
- named/forced tool choice
- structured output
- reasoning effort support
- vision input
- image tool results
- screenshot vision
- semantic browser control (DOM/CDP)
- semantic macOS control (Accessibility/AX)
- pixel/coordinate computer use

Unknown support is **unknown**, not implicitly true because of a provider or
model family name.

## Controller vs helper

The controller owns the conversation. A helper satisfies one bounded capability
and returns a structured observation to the controller. A helper must not
silently replace the controller session.

```text
Muse controller
  -> needs visual diagnosis
  -> approved vision helper receives bounded screenshot/crop
  -> helper returns structured observation
  -> Muse continues the original session
```

A helper receipt must identify controller provider/model, helper provider/model
or local engine, capability/reason, correlation id, attempts, and billable
usage/cache data when applicable.

## Routing policy modes

The public policy should support at least:

- `strict`: primary controller only; unsupported capability fails locally.
- `smart_local`: primary controller plus explicitly implemented local semantic
  or visual helpers.
- `smart_go`: primary controller plus explicitly allowed OpenCode Go helpers.
- `custom`: user-declared per-capability routes/helper allowlists.

No helper is permitted merely because credentials exist.

## Computer-use observation order

Prefer the least expensive, most semantic path:

1. shell/API/MCP
2. browser DOM/CDP
3. macOS Accessibility/AX
4. screenshot/vision helper
5. coordinate action only when semantics are insufficient

A non-vision controller must be able to perform semantic computer use without
receiving pixels.

## Retry, helper routing, and failover are different

Do not overload one fallback mechanism.

### Retry

Transient recovery for the same provider/model. Existing bounded,
commit-aware retry semantics remain authoritative.

### Capability helper

A subordinate operation for a capability the controller lacks. It is allowed
only by session policy.

### Controller failover

Replacing the primary model. Default OFF. Never automatically replay committed
model output or tool side effects on a different controller.

## Isolation contract

Capability routing integrates with provider/subscription isolation (#22). For
an OpenCode Go session by default:

- OpenCode Go controller calls are allowed;
- local helpers are allowed only when configured by policy;
- Go helper models are allowed only when explicitly listed;
- Anthropic, OpenAI/Codex, ChatGPT, and other paid provider families remain
  forbidden unless explicitly enabled;
- helper availability must never be inferred from unrelated credentials found
  on disk.

## Failure behavior

Unsupported capability must fail before an upstream request when no permitted
route exists. The error should state the required capability, selected
controller, why it cannot satisfy the request, whether helpers are disabled or
forbidden, and how to select an explicit route without implicitly suggesting a
paid provider.

No silent modality dropping, image omission, named-tool coercion, or controller
substitution.

## Cache and economics

Helper routing should preserve the controller's stable prefix where possible.
Do not resend large media/helper transcripts into controller context when a
bounded structured observation is sufficient.

Receipts should permit comparison of controller cache-read share, effective
uncached input, helper tokens/cost, attempts, and stable-prefix hash.

## Test matrix

Deterministic tests must cover:

1. capability extraction for text, tools, parallel tools, images and computer
   use;
2. explicit provider/model capability metadata;
3. blind controller + image in `strict` -> typed local failure with zero
   upstream call;
4. blind controller + approved helper -> helper only, original controller
   continues;
5. semantic computer use with blind controller -> no vision helper call;
6. pixel-dependent task -> approved vision helper route;
7. forbidden helper provider -> typed local failure;
8. same-provider retry remains independent from helper routing;
9. committed tool side effect -> no automatic controller failover/replay;
10. receipts identify controller/helper/reason without payload leakage.

Live acceptance should include a Muse controller performing semantic computer
use and one bounded approved vision-helper workflow.

## Integration boundaries

Extend rather than replace the working routing/provider/receipt primitives,
#19 visual attachments, #20 local computer use, #21 browser control, and #22
provider isolation.

Avoid a router model, a second orchestration runtime, or a rewrite of the
working OpenCode Go/Muse transport.
