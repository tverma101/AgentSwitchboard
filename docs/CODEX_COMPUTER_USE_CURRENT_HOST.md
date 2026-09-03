# Current Codex Computer Use host contract

This note supplements `CODEX_COMPUTER_USE_UPSTREAMS.md` with newer compatibility
evidence found while implementing the Codex Computer Use host seam. The earlier
issue references are historical traceability; native/device acceptance remains
a separate evidence boundary rather than an open-backlog claim.

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

AgentSwitchboard does not import OpenClaw runtime ownership or plugin mutation logic.

### iFurySt/open-codex-computer-use

- source pin reviewed: `ead48da2032c69b892c89fd39d38fa587b4d6fbf`
- reviewed `scripts/computer-use-cli/app_server.go` and sender-auth/version-history notes.

Important compatibility warning: older observed Computer Use builds could list MCP tools through app-server while actual calls were rejected by service-side sender authorization. Binary existence and `tools/list` are therefore not sufficient native-parity evidence. Current AgentSwitchboard must require a positive managed-host probe on the installed build.

## AgentSwitchboard implementation split

`CodexComputerUseBroker` remains the isolated direct-client diagnostic path derived from the earlier MIT upstreams.

`ManagedCodexComputerUseBroker` is the native-parity candidate. It:
- mirrors the current bundled plugin launcher when present;
- refuses the retired direct-client path when the bundled launcher is absent;
- enables current app-server feature flags;
- disables model execution paths with a dead provider and zero retries;
- strips ambient OpenAI/Codex API credentials by constructing a minimal child environment;
- uses the user's Codex component home only for the managed plugin/runtime state required by the official launcher;
- creates an ephemeral, on-request, workspace-write thread with only the `computer-use` MCP server configured;
- polls `mcpServerStatus/list` and fails closed unless all ten expected native tools appear;
- exposes native tool names/auth state only as runtime evidence, never as dynamic Luna tool-schema input;
- defaults low-level elicitations to cancel; the FCC Claude MCP server supplies
  an explicit `auto` handler only when `codex-computer-use` is allow-listed,
  while `FCC_COMPUTER_USE_APPROVAL=decline` keeps the user-facing bridge
  fail-closed;
- reports mutating timeout/transport loss as **indeterminate** instead of retrying;
- retains the zero-Codex-model-turn fatal guard inherited from the base broker.

For the normal `fcc-claude` launch, FCC validates the signed installation and
exposes the official skill through the active Claude profile. It registers the
FCC-owned local MCP name to the Python FCC MCP module
(`free_claude_code.cli.codex_computer_use_mcp`). That server starts the signed
Codex `app-server`, creates an ephemeral on-request thread, configures the
official bundled Computer Use plugin launcher, waits for all ten native tools,
and dispatches calls through `mcpServer/tool/call`. It answers the native
elicitation handshake and preserves structured screenshot blocks. Read-only
state/list calls get one bounded connection-recovery attempt; mutating calls
are never replayed after an uncertain result. The old vendored Node bridge is
kept only as a narrowly identified migration entry for older FCC installs;
it is not the normal Claude MCP path. The signed native client remains
unmodified.

The registration is project-local and the Claude launcher does not replace or
silently remove other user-owned MCP servers. FCC does not set Claude's
`MAX_MCP_OUTPUT_TOKENS` result budget; user and Claude Code policy remain in
control. The FCC server still rejects any future Computer Use tool-schema
expansion beyond its fixed 16 KiB contract, preserving native structured
screenshot blocks.

### Structured result transport boundary

The FCC MCP server returns the native MCP response with its JPEG screenshot
block intact. It does not turn a screenshot into text, alter element IDs, or
make a second model request. Claude integrations may replay either that
response or a complete MCP `CallToolResult`/JSON-RPC result envelope inside
Anthropic `tool_result.content`; the FCC compatibility boundary still owns
provider-specific media conversion. Unsupported nested media remains
fail-closed rather than being flattened into misleading text.

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
