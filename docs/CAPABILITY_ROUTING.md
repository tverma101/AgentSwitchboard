# Capability-aware routing

Tracks #30. This document defines the runtime contract for capability-aware routing. It intentionally does not change production routing by itself.

## Why this exists

`ModelRouter` currently resolves a Claude-facing model name to one configured provider/model and reasoning policy. That is necessary but insufficient once a request can require capabilities the selected controller model does not have.

Examples:

- a blind controller receives an image attachment;
- computer use can be solved semantically through DOM/AX without pixels;
- a request asks for named tool choice but the upstream supports only `auto`;
- a screenshot needs a vision helper while the original controller should remain in charge;
- a helper is available but belongs to a provider the session is not allowed to bill.

Capability routing must make those decisions explicitly and before upstream spend.

## Required capability set

Derive a deterministic `RequiredCapabilitySet` from the request and requested tool workflow. The vocabulary must be explicit and extensible. Initial capabilities:

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

Unknown support is **unknown**, not implicitly true because of a provider or model family name.

## Controller vs helper

The controller is the model that owns the conversation. A helper satisfies one bounded capability and returns a structured observation to the controller.

A helper must not silently replace the controller session.

Example:

```text
Muse controller
  -> needs visual diagnosis
  -> approved vision helper receives bounded screenshot/crop
  -> helper returns structured observation
  -> Muse continues the original session
```

A helper receipt must identify:

- controller provider/model
- helper provider/model or local engine
- capability/reason
- turn/request correlation id
- attempts
- token/cache data when billable

## Routing policy modes

The public policy should support at least:

- `strict`: primary controller only; unsupported capability produces a typed local error.
- `smart_local`: primary controller plus explicitly implemented local semantic/visual helpers.
- `smart_go`: primary controller plus explicitly allowed OpenCode Go helper routes.
- `custom`: user-declared per-capability routes and helper allowlists.

No helper is permitted merely because credentials exist.

## Computer-use observation order

Prefer the least expensive, most semantic path:

1. shell/API/MCP
2. browser DOM/CDP
3. macOS Accessibility/AX
4. screenshot/vision helper
5. coordinate action only when semantics are insufficient

A non-vision controller must be able to perform semantic computer use without receiving pixels.

## Retry, helper routing, and failover are different

Do not overload one fallback mechanism.

### Retry

Transient recovery for the same provider/model. Existing bounded retry/commit-aware semantics remain authoritative.

### Capability helper

A subordinate operation for a capability the controller lacks. It is allowed only by session policy.

### Controller failover

Replacing the primary model. Default OFF. Never automatically replay committed model output or tool side effects on a different controller.

## Isolation contract

Capability routing integrates with provider/subscription isolation (#22).

For an OpenCode Go session by default:

- OpenCode Go controller calls are allowed;
- local helpers are allowed only when configured by policy;
- Go helper models are allowed only when explicitly listed;
- Anthropic, OpenAI/Codex, ChatGPT, and other paid provider families remain forbidden unless explicitly enabled;
- helper availability must never be inferred from unrelated credentials found on disk.

## Failure behavior

Unsupported capability must fail before an upstream request when no permitted route exists. The error should state:

- required capability;
- selected controller;
- why it cannot satisfy the request;
- whether helpers are disabled, unavailable, or forbidden by policy;
- how to choose an explicit route without suggesting a paid provider implicitly.

No silent modality dropping, image omission, named-tool coercion, or controller substitution.

## Cache and economics

Helper routing should preserve the controller's stable prefix whenever possible. Do not resend large image payloads or helper transcripts into the controller context when a bounded structured observation is sufficient.

Receipts should permit comparison of:

- controller cache-read share before/after helper use;
- effective uncached input;
- helper tokens/cost;
- attempts per turn;
- stable-prefix hash.

## Test matrix

Deterministic tests must cover:

1. capability extraction for text-only, tools, parallel tools, image input, image tool result, and computer-use requests;
2. explicit provider/model capability metadata;
3. blind controller + image in `strict` mode -> typed local failure with zero upstream call;
4. blind controller + image with approved helper -> helper only, then original controller continues;
5. semantic computer-use path with blind controller -> no vision helper call;
6. pixel-dependent task -> approved vision helper route;
7. forbidden helper provider -> typed local failure;
8. same-provider retry remains independent from helper routing;
9. committed tool side effect -> no automatic controller failover/replay;
10. receipts identify controller/helper/reason without prompt or secret leakage.

Live acceptance should include a Muse controller performing semantic computer use and one bounded approved vision-helper workflow.

## Integration boundaries

This work should extend, not replace:

- `free_claude_code.application.routing.ModelRouter`
- provider capability metadata/contracts
- fault attribution and attempt receipts
- #19 visual attachments
- #20 local computer use
- #21 browser/CDP
- #22 provider/subscription isolation

Avoid a router model, a second orchestration runtime, or a rewrite of the working OpenCode Go/Muse transport.
