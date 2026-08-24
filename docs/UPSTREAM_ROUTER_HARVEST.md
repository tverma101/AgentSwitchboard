# Upstream Router Harvest Plan

This document turns external prior art into bounded implementation work for Harness capability routing. It is intentionally source- and license-aware: upstream projects are code mines and test-oracle sources, not drop-in runtime dependencies.

## Rules

1. Keep the current Harness Muse/OpenCode Go transport, receipt model, retry safety, 256K context policy, learning bridge, and provider isolation.
2. Prefer the smallest reusable unit over importing an upstream router/runtime.
3. Record the upstream repository, exact commit SHA, file/function, license, and whether code was copied, adapted, or only behaviorally referenced.
4. MIT code may be adapted with required attribution/license preservation.
5. Code with unclear licensing is reference-only. Do not copy it.
6. Known upstream bugs become regression fixtures before equivalent Harness code is considered complete.
7. A skipped live test is UNVERIFIED, not PASS.

## Source matrix

### musistudio/claude-code-router

Repository: https://github.com/musistudio/claude-code-router
License: MIT.
Primary issues: #39, #41, #42.

Harvest candidates:
- Fusion Vision capability composition: vision helper observes images/screenshots/OCR while the base/controller model continues the task.
- Request-aware routing predicates such as image/tool presence.
- Explicit retry/fallback configuration shapes.
- Request/agent observability patterns useful for helper receipts.
- Fusion MCP/tool composition concepts where they reduce custom glue.

Do not assume upstream correctness. Convert at least these known failures into Harness regression fixtures:
- https://github.com/musistudio/claude-code-router/issues/1678 — images silently dropped during Anthropic -> OpenAI chat translation.
- https://github.com/musistudio/claude-code-router/issues/1643 — tool_result loss on an OpenAI Responses route.

Harness-specific requirement: a helper augments the controller; it must not silently replace the whole Muse conversation or escape #22 provider policy.

### hishamkaram/claude-code-router

Repository: https://github.com/hishamkaram/claude-code-router
License: MIT.
Primary issue: #40.

Harvest candidates:
- explicit capability truth with supported / unsupported / unknown semantics.
- capability evidence precedence rather than provider-name guessing.
- pre-provider rejection for unsupported vision, tools, thinking, structured output, and computer use.
- explicit managed computer-use executor boundary.
- diagnostics/doctor-style compatibility reporting.
- live verification discipline: skipped real tests are not evidence.

Harness-specific requirement: capability diagnostics must integrate with existing fault/receipt telemetry and never log secrets or user payloads.

### BerriAI/litellm

Repository: https://github.com/BerriAI/litellm
License: MIT for non-enterprise code. `enterprise/` has separate licensing and is out of bounds.
Primary issue: #42.

Harvest candidates:
- separation and ordering of retry/fallback targets.
- context-window-specific fallback concepts.
- health/rate-limit-aware route eligibility.
- tests/data structures for explicit fallback chains.

Do not add LiteLLM as a runtime dependency merely to obtain routing policy. Preserve Harness invariants: controller failover OFF by default, capability/context eligibility before fallback, and no cross-controller replay after committed output or tool execution.

### vasic-digital/claude-code-router

Repository: https://github.com/vasic-digital/claude-code-router
License status: its README states the Go implementation currently lacks a confirmed top-level license; upstream MIT text is retained separately. Treat the Go implementation as reference-only unless licensing is clarified.
Primary issue: #41.

Behavioral reference only:
- base64/URL image translation.
- image content inside tool_result/computer-use screenshots.
- named errors for malformed/unsupported media instead of silent stripping.

Do not copy source from this implementation under the current license state.

## Required implementation order

1. #41 media conformance corpus first. Silent media loss must become impossible before helper routing is enabled.
2. #40 explicit capability truth and local preflight.
3. #39 bounded Fusion-style vision helper while preserving the controller session.
4. #42 typed fallback policy only after capability/context eligibility exists.
5. Integrate the resulting pieces into #30 and the provider/subscription policy in #22.

## Required receipts

Each harvested implementation PR must include:
- upstream repository and exact source commit SHA.
- license classification and attribution action.
- files/functions adapted or behaviorally referenced.
- deterministic tests added.
- known upstream bug fixtures covered.
- controller/helper/provider route receipt.
- attempt/retry/fallback reason.
- media counts/types when relevant, never media payloads.
- cache/economic impact when the controller prefix is affected.
- residual unverified live capability explicitly marked UNVERIFIED.

## Non-goals

- replacing Harness with another router.
- importing an Electron/desktop control plane.
- adding an autonomous routing LLM.
- copying code with unclear licensing.
- silently changing controller models to make an unsupported request succeed.
