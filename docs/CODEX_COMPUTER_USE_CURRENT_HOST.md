# Current Codex Computer Use host contract

This note supplements `CODEX_COMPUTER_USE_UPSTREAMS.md` with newer compatibility evidence found while implementing #102/#103.

## Current primary evidence

### fitchmultz/macuse

- source pin: `447df5214c143c7e88e644295451fc81fee71d70`
- reviewed files:
  - `docs/reference/codex-computer-use-external-harness.md`
  - `tools/codex-computer-use-appserver.mjs`
  - `tools/macuse-utils.mjs`
- observed/validated through August 2026.

Current working external-harness shape:

1. launch the signed bundled Codex `app-server`;
2. enable `computer_use`, `plugins`, and `tool_call_mcp_elicitation`;
3. initialize with current experimental app-server capabilities;
4. start one ephemeral thread with `approvalPolicy=on-request`;
5. configure `computer-use` using the bundled plugin's `bin/computer-use-client-launcher`, `args=["mcp"]`, plugin cwd, and forwarded `CODEX_HOME`;
6. poll thread-scoped `mcpServerStatus/list` using `detail=toolsAndAuthOnly` until the native server exposes all ten Computer Use tools;
7. invoke only through `mcpServer/tool/call`;
8. answer `mcpServer/elicitation/request` explicitly with accept/decline/cancel;
9. do not blindly replay mutating calls after timeout/transport loss.

The same source has guarded positive evidence for `list_apps`, `get_app_state`, click, key press, scroll, `type_text`, `set_value`, and `select_text` on controlled macOS targets. Drag/high-stakes workflows remain device acceptance work.

### openclaw/openclaw

- source pin reviewed: `c2602193d630db55b1d2739e490163cd73c6ccb3`
- reviewed current Codex extension Computer Use readiness/lifecycle code.

Useful patterns adapted conceptually:
- MCP startup is asynchronous; treat inventory/readiness as a real state rather than assuming spawn means ready;
- a lightweight live `list_apps` probe is the safest positive health check;
- reload/retry can be reasonable for read-only health, but mutation replay needs a stronger side-effect boundary.

Harness does not import OpenClaw runtime ownership or plugin mutation logic.

### iFurySt/open-codex-computer-use

- source pin reviewed: `ead48da2032c69b892c89fd39d38fa587b4d6fbf`
- reviewed `scripts/computer-use-cli/app_server.go` and sender-auth/version-history notes.

Important compatibility warning: older observed Computer Use builds could list MCP tools through app-server while actual calls were rejected by service-side sender authorization. Binary existence and `tools/list` are therefore not sufficient native-parity evidence. Current Harness must require a positive managed-host probe on the installed build.

## Harness implementation split

`CodexComputerUseBroker` remains the isolated direct-client diagnostic path derived from the earlier MIT upstreams.

`ManagedCodexComputerUseBroker` is the native-parity candidate. It:
- mirrors the current bundled plugin launcher when present;
- falls back to the already verified signed client only if the launcher is absent;
- enables current app-server feature flags;
- disables model execution paths with a dead provider and zero retries;
- strips ambient OpenAI/Codex API credentials by constructing a minimal child environment;
- uses the user's Codex component home only for the managed plugin/runtime state required by the official launcher;
- creates an ephemeral, on-request, workspace-write thread with only the `computer-use` MCP server configured;
- polls `mcpServerStatus/list` and fails closed unless all ten expected native tools appear;
- exposes native tool names/auth state only as runtime evidence, never as dynamic Luna tool-schema input;
- defaults all elicitations to cancel unless an explicit policy handler decides otherwise;
- reports mutating timeout/transport loss as **indeterminate** instead of retrying;
- retains the zero-Codex-model-turn fatal guard inherited from the base broker.

## Cache boundary

Runtime inventory, plugin paths, launcher paths, Codex home, auth status, thread ids, plugin versions, timestamps and elicitations remain outside Luna's fixed cacheable tool contract. The controller-facing ten-tool contract still comes from code-owned deterministic definitions.

The native inventory is validation evidence only. A plugin update must never rewrite/reorder Luna's tool schema mid-session.

## Remaining native acceptance

A real Apple-silicon Mac must still prove on the same installed build:
- managed server reaches ready with all ten tools;
- `list_apps` positive live probe;
- `get_app_state` screenshot + semantic state;
- controlled action matrix versus native Codex Desktop;
- elicitation/TCC behavior;
- interruption/timeout produces no duplicate action;
- zero Codex model turns;
- Luna prefix/tool/history hashes remain stable and Go cache economics do not regress materially.
