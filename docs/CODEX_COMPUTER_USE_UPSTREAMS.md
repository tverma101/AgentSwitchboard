# Codex Computer Use upstream reuse

Harness must reuse the signed Codex/ChatGPT Computer Use host path rather than building another macOS automation stack.

## Primary upstream: tmustier/codex-computer-use-mcp

- Repository: https://github.com/tmustier/codex-computer-use-mcp
- Source pin: `e90efa7bf83cd7a2a8b821c568bf20da4c894c12` (release v0.5.0, 2026-08-22)
- License: MIT
- Best reference for production invariants, signature verification, zero-model-turn direct dispatch, cleanup, elicitation forwarding, and exact tool schemas.

Important implementation facts at this pin:

- verifies the app-bundled Codex binary and Computer Use client are signed by OpenAI Team ID `2DC432GLL2`;
- resolves the current per-user Computer Use component under `~/.codex/computer-use/Codex Computer Use.app`, with the reviewed legacy bundled-plugin layout only as fallback;
- starts `/Applications/ChatGPT.app/Contents/Resources/codex app-server --stdio` with an isolated temporary `CODEX_HOME`;
- configures only the official Computer Use MCP server and disables model/provider/plugin/history/memory/telemetry paths;
- sends app-server `initialize`, `initialized`, then an ephemeral `thread/start`;
- dispatches each operation through `mcpServer/tool/call` with `{threadId, server: "computer-use", tool, arguments}`;
- treats any `turn/*` or `item/*` event as a failure, proving Computer Use can run with zero Codex model turns;
- reuses one signed session so `get_app_state` element identifiers remain valid for following actions;
- exposes the exact ten observed Computer Use methods: `list_apps`, `get_app_state`, `click`, `perform_secondary_action`, `set_value`, `select_text`, `scroll`, `drag`, `press_key`, `type_text`;
- keeps audit records metadata-only and verifies process-tree cleanup.

Harness should PORT/ADAPT the smallest Python-equivalent broker behavior and tests; do not depend on this Node package at runtime unless that proves materially simpler.

## Secondary upstream: manaflow-ai/codex-cua

- Repository: https://github.com/manaflow-ai/codex-cua
- Source pin: `3073c1f8ae63f1747b1b8648955c95389d4c7446` (2026-07-27)
- License: MIT
- Single ~29.6 KB Python stdlib CLI, especially useful because Harness is Python.

Its `AppServer` class demonstrates the minimal transport:

1. resolve Codex + `SkyComputerUseClient`;
2. spawn `codex app-server --stdio` with MCP config overrides;
3. `initialize`;
4. `initialized`;
5. ephemeral `thread/start`;
6. `mcpServer/tool/call` for the official Computer Use method;
7. keep one warm app-server/thread when low latency is desired.

It also demonstrates the critical state rule: interaction tools require a `get_app_state` for the same app first, and element indices belong to the snapshot/session that produced them.

## Official Codex source contract

OpenAI's public `codex-rs/app-server` documents `mcpServer/tool/call` as a direct call to a configured MCP server. This is the host surface to rely on; do not reverse-engineer the private Computer Use service socket.

## Harness decision

Use the upstream pattern:

`Luna/Claude Code -> fixed Harness Computer Use tools -> signed Codex app-server -> signed SkyComputerUseClient -> official Computer Use service -> macOS app`

Computer Use itself requires **zero Codex model turn**. Codex-model delegation remains a separate optional feature.

### Cache invariant

The Harness-facing tool definitions must be deterministic and fixed at Claude/Luna session start. Auth status, component paths, plugin versions, app inventories, thread IDs, timestamps, and runtime diagnostics stay outside Luna's cacheable tool/system prefix. A Computer Use call appends only the new tool result.

### Do not copy blindly

The `tmustier` implementation has stronger production hardening than the smaller `manaflow-ai` script. Prefer its signature/path verification, zero-turn assertions, elicitation handling, model-disable controls, and cleanup semantics. Use `manaflow-ai/codex-cua` as the small Python transport reference.
