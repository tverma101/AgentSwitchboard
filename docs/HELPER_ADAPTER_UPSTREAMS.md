# Approved helper adapter upstream decisions

Issue #45 asks AgentSwitchboard to harvest only the useful Fusion MCP/ToolHub composition ideas without importing a second router, browser runtime, computer runtime, Electron shell, or generic autonomous orchestration layer.

## Primary upstream reviewed

`musistudio/claude-code-router`

- source pin: `99f24806c6a2c660b16e53e95211c517448a6c90`
- license: MIT
- reviewed areas:
  - `packages/core/src/mcp/tool-discovery.ts`
  - `packages/core/src/mcp/toolhub-config.ts`
  - `packages/core/src/mcp/toolhub-mcp.ts`
  - `packages/core/src/mcp/fusion-config.ts`
  - `packages/core/src/mcp/fusion-tool-fallback-mcp.ts`
  - Fusion MCP documentation

The upstream MIT license is recorded in its root `LICENSE` at the source pin.

## PORT / ADAPT / REJECT decisions

### ADAPT — one explicit helper registry

AgentSwitchboard now has `ApprovedHelperRegistry`. Implementations are registered by repo/user-owned startup code and the registry can be frozen before a session. Registration is deterministic and exposes the existing `CapabilityHelper` metadata used by #30.

This keeps the useful ToolHub idea — one place to describe available helpers — without allowing filesystem/network discovery to become authorization.

### REJECT — generic hot-path MCP discovery

The upstream supports stdio, streamable HTTP and legacy SSE tool discovery. AgentSwitchboard does not need a generic remote-MCP crawler in the controller request path.

Transport discovery remains adapter-owned and outside Luna's hot/cacheable request path. An approved helper can internally use stdio or another reviewed transport, but mere discovery never registers or authorizes it.

### ADAPT — explicit capability declarations

Each `ApprovedHelper` declares a fixed `frozenset[Capability]`. `router_helpers()` returns the already-shipped #30 `CapabilityHelper` structure rather than introducing another capability vocabulary/router.

### ADAPT — bounded timeout and cancellation

`ApprovedHelperExecutor` runs one attempt, gives the helper a cancellation event, returns controller control at the configured deadline, and never performs implicit retries.

If the helper acknowledges cancellation and terminates during the short grace period, the result is `timed_out`. If termination cannot be proved, the result is `indeterminate`. This distinction prevents automatic replay of potentially committed browser/computer side effects.

### ADAPT — provider/subscription guard before execution

Every helper execution passes the existing #22 `ProviderEgressGuard` before the helper thread starts. Local tools use the existing `local_tool` category; provider-backed helpers remain subject to the configured provider family policy.

Credentials, binaries, or a registered callable do not themselves authorize execution.

### ADAPT — one bounded structured result contract

Helpers return a JSON-compatible mapping. The executor measures the serialized result and rejects output above the helper's fixed byte limit rather than injecting an unbounded transcript into the controller context.

Receipts contain only helper/provider/operation/status/duration/attempt/failure-owner/output-size metadata. Arguments and output content are not copied into receipts.

### REJECT — implicit fallback helper

The Fusion fallback MCP pattern is not imported. The existing #30 route plan must select a helper first, and `execute_planned()` refuses any helper not already selected by that route.

Retry, helper routing, and controller failover remain separate concepts. `attempts` is intentionally `1` in this executor.

### REJECT — Electron/runtime ownership

No Electron dependency, daemon, generic MCP process manager, browser runtime, computer runtime, or alternate provider router is added.

## First concrete adapters

The Codex Computer Use work in #102/#103 is the first target for this seam:

`Luna -> #30 capability plan -> ApprovedHelperExecutor -> signed Codex Computer Use broker`

The existing browser/Appshot/Fusion Vision adapters can use the same typed seam later without changing the router or execution contract.

## Acceptance mapping for #45

- one registry for approved existing helpers: implemented;
- discovery outside request hot path: implemented by explicit registration/freeze; no automatic discovery exists;
- explicit capability declarations: implemented via existing `Capability` / `CapabilityHelper`;
- bounded timeout/cancellation: implemented with timed-out vs indeterminate receipts;
- structured bounded result: implemented with JSON + byte limit;
- provider isolation: existing `ProviderEgressGuard` runs before helper code;
- helper receipts: helper id, provider family, operation, duration, attempts, failure owner, local/billable and output byte count;
- no automatic retry or controller replacement: implemented;
- idle overhead: registry is in-memory metadata only; executor creates a daemon worker only for an actual helper invocation;
- no network/filesystem discovery: implemented;
- no Electron/new runtime dependency: implemented.
