# Upstream router and tool harvest plan

> **Status: active implementation-source plan.** This is not a runtime dependency
> list. Re-verify upstream license/behavior before copying code. Keep AgentSwitchboard's
> Claude/OpenCode Go compatibility, provider isolation, receipts, retry safety,
> and context policy as the owned core; harvest bounded pieces instead of
> rebuilding mature browser/tool/router machinery.

## Rules

1. Prefer **fork/adapt/wrap/test-only** over greenfield implementation.
2. Record upstream repository, exact commit SHA, file/function, license, and
   whether code was copied, adapted, wrapped, or only behaviorally referenced.
3. MIT code may be adapted with required attribution/license preservation.
4. Unclear licensing is reference-only: do not copy source.
5. Convert relevant upstream bugs into AgentSwitchboard regression fixtures.
6. A skipped live test is UNVERIFIED, not PASS.
7. Do not replace the working AgentSwitchboard transport/control plane with a third-party
   router merely because that router contains useful components.

## musistudio/claude-code-router

Repository: `https://github.com/musistudio/claude-code-router`

Harvest candidates include Fusion Vision/helper composition, request-aware
routing predicates, explicit retry/fallback shapes, Agent Profile UX concepts,
Fusion MCP composition, observability patterns, and regression cases from
upstream protocol/image/tool bugs.

AgentSwitchboard-specific rule: helpers augment the controller; they do not silently
replace the Muse conversation or escape provider policy.

## hishamkaram/claude-code-router

Repository: `https://github.com/hishamkaram/claude-code-router`

Harvest explicit supported/unsupported/unknown capability truth, evidence
precedence, pre-provider capability rejection, diagnostic/doctor patterns, and
managed computer-use executor boundaries. Integrate diagnostics with existing
AgentSwitchboard receipts rather than creating a second telemetry system.

## LiteLLM

Repository: `https://github.com/BerriAI/litellm`

Use non-enterprise MIT code/patterns only where licensing permits. Useful prior
art includes retry/fallback ordering, context-window eligibility concepts, and
health/rate-limit-aware route eligibility. Do not add LiteLLM as a runtime
dependency merely to obtain routing policy.

## Microsoft Playwright

Repository: `https://github.com/microsoft/playwright`

**Preferred browser source before greenfield CDP work.** Playwright's official
CLI/MCP support already provides semantic browser interaction, accessibility
snapshots, forms/navigation, screenshots, persistent sessions, and Claude Code
integration patterns.

For the historical browser-control requirement, first determine whether a thin
AgentSwitchboard wrapper around Playwright CLI or MCP satisfies the requirement.
The earlier issue reference is historical traceability, not an open-backlog
claim. Prefer CLI/skills when that materially reduces
tool/context overhead; prefer MCP for a persistent specialized browser loop.
Only write custom CDP machinery for concrete gaps that Playwright cannot cover.

AgentSwitchboard should add provider policy, bounded receipts, session safety, and any
missing integration glue rather than recreating browser automation.

## mac-use

Repository: `https://github.com/entpnomad/mac-use`

**Audit before greenfield macOS AX work.** The project uses native macOS
Accessibility/System Events/AppleScript concepts and can provide code/prior art
for semantic UI control. Verify license and implementation quality at the exact
revision before copying anything.

For #20, harvest/wrap suitable semantic AX primitives first. Keep AgentSwitchboard-owned
permission/safety policy, receipts, provider independence, and any missing
ScreenCaptureKit/CGEvent/AppKit integration.

## vasic-digital/claude-code-router

Repository: `https://github.com/vasic-digital/claude-code-router`

Treat implementation source as reference-only unless current licensing is
confirmed. Useful behavioral references include image translation, image
content inside tool results/computer-use screenshots, and explicit malformed or
unsupported-media errors instead of silent stripping.

## Preferred implementation order

1. media conformance fixtures: silent modality loss must be impossible;
2. explicit capability truth/preflight;
3. browser: wrap/harvest Playwright before custom CDP expansion;
4. macOS semantic control: audit/harvest mac-use before greenfield AX;
5. bounded vision/helper composition while preserving controller identity;
6. typed fallback only after capability/context eligibility exists;
7. integrate with #30 routing and #22 provider isolation.

## Required receipts for harvested work

Each implementation PR should identify upstream source+commit, license action,
files/functions adapted or behaviorally referenced, deterministic tests, known
upstream bug fixtures, controller/helper/provider route, retry/fallback reason,
media counts/types without payloads, cache/economic impact where relevant, and
remaining live gaps as UNVERIFIED.

## Non-goals

- replacing AgentSwitchboard with another router;
- importing an Electron/desktop control plane;
- adding an autonomous routing LLM;
- copying unclearly licensed code;
- silently changing controller models to make unsupported requests succeed.
