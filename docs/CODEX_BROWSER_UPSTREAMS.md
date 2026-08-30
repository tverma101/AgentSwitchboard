# Codex browser upstream harvest

This is a provenance and design note for the browser-helper seam. The earlier
issue reference is historical traceability, not an open-backlog claim. This
branch treats public repositories as a parts bin and keeps Luna as the
controller. It does **not** add Playwright as a required runtime and does not
rebuild a CDP/browser engine.

## Primary port: Botmux

- Repository: `deepcoldy/botmux`
- Pin: `eff1953a66fe6054f47d9311c719ab73c4ed6f1d`
- License: MIT
- Source: `src/services/codex-browser-broker.ts` and `test/codex-browser-broker.test.ts`

Useful implementation already proven upstream:

- discovers the installed Codex `openai-bundled/chrome` plugin instead of copying OpenAI plugin code;
- loads `scripts/browser-client.mjs` and `scripts/browser-service.mjs` directly;
- supplies the small `nodeRepl`/native-pipe/config shim expected by that installed plugin;
- obtains the real Chrome/Edge browser binding from `agent.browsers.get(...)`;
- requires an explicit claim before operating an existing user tab;
- exposes a bounded semantic operation vocabulary rather than arbitrary JavaScript/raw CDP;
- caps text, screenshots, values, URLs and operation duration;
- cancels plugin elicitation rather than inventing approval;
- has deterministic fakes for tab discovery/claim, AX actions, screenshots and plugin discovery.

AgentSwitchboard adapts that shape into one lazy local approved helper. The helper is subordinate to the existing #30/#104 capability route and #105 egress policy. Luna remains the controller.

## Transport/runtime corroboration: codex-desktop-linux

- Repository: `ilysenko/codex-desktop-linux`
- Pin: `ba8097eeee0b249aacaa32569e5cf73b5c1dd718`
- License: MIT
- Sources: `computer-use-linux/src/bin/codex-chrome-extension-host.rs`, `computer-use-linux/src/chrome_runtime.rs`

This code independently implements the current Unix native-host/browser runtime shape with `UnixListener`/`UnixStream`, bounded socket paths, native-host protocol v2, runtime manifests and app-server proxy lifecycle. It is evidence that the macOS/Linux gap is not a reason to invent a second browser protocol. AgentSwitchboard does not vendor this runtime because the user's Codex/ChatGPT installation already owns the native host.

## Broader MCP bridge: codex-browser-bridge

- Repository: `DeliciousBuding/codex-browser-bridge`
- Pin: `c692fb017d79d458927c6a8e350dc2d06224d46e`
- License: MIT

Useful as a protocol/tooling reference: it exposes the Codex desktop browser bridge to MCP clients and demonstrates a much larger tool surface. AgentSwitchboard deliberately does **not** copy all 52 operations into Luna's stable tool prefix. A small semantic helper is easier to authorize, cache and audit.

## Deterministic browser API mock: Storybook

- Repository: `storybookjs/storybook`
- Pin: `457f8e44a64cca45dccb073252ee6a29dbe00e16`
- License: MIT
- Source: `agent-eval/lib/mcp/codex-browser-client-mock.mjs`

Storybook implements the same `agent.browsers.*` shape used by Codex's in-app browser and records behavioral details such as viewport, JPEG screenshots, AX/DOM snapshots, locator deadlines, console logs and CDP capability boundaries. AgentSwitchboard may use the API shape/fixtures for deterministic contract tests, but must not adopt its Playwright-backed mock as a production browser runtime.

## Claude MCP registration reference

- Repository: `joshrotenberg/claude-wrapper`
- Pin: `b87432fe5b8fb87c2e7f1135e5cc21006a86150e`
- License: Apache-2.0
- Source: `src/command/mcp.rs`

Confirms the supported persistent Claude CLI management surface: `claude mcp add-json --scope ...`, `get`, `list`, and scoped `remove`. Reuse that official CLI boundary for persistent Claude registration; do not edit Claude's internal JSON state directly.

## Port / adapt / reject

**PORT/ADAPT**
- installed Codex plugin discovery;
- small trusted runtime shim;
- native-pipe connection delegated to Node's platform transport;
- explicit user-tab claim;
- bounded AX/browser operations;
- warm helper process with one serialized request stream;
- fail-closed approval behavior;
- deterministic mock contracts.

**REJECT**
- a second CDP engine;
- a mandatory Playwright runtime;
- arbitrary JavaScript or raw CDP in Luna's normal helper surface;
- cookies/local-storage/history/clipboard/file-transfer exposure by default;
- copying the closed-source installed Codex browser plugin;
- dynamic discovery of tools in Luna's hot prompt path;
- direct mutation of Claude internal config files.

## Remaining real-machine proof

Repository tests can prove the bounded adapter and protocol shape. A real macOS acceptance receipt must still prove the installed current Codex/ChatGPT plugin can `list_tabs`, explicitly claim a test tab, snapshot it, perform one controlled action, and capture one screenshot. Until that receipt exists, this branch is staged implementation rather than native certification.
