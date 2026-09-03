# Codex subscription bridge — design checkpoint

This document is a placeholder design checkpoint and is not a release claim.

## Goal

Keep Claude Code + Luna as the primary controller while allowing explicit, bounded delegation to a locally installed Codex runtime authenticated with the user's ChatGPT plan. Do not require or persist a manually supplied OpenAI API key.

## Live Responses-Lite wire contract

Both FCC server modes enable a model-scoped Codex Responses-Lite adapter for
the audited `gpt-5.6-luna`, `gpt-5.6-sol`, and `gpt-5.6-terra` IDs. Other
OpenAI models keep the generic Responses request shape.

For those exact model IDs, the adapter:

- puts translated function tools in the first `additional_tools` developer
  input item under the `functions` namespace, with thread-scoped stable
  prompt-only item IDs (`lite_item_id`, namespaced by the Claude session
  thread like native `Uuid::new_v5` under the thread);
- puts the bounded Codex compatibility base and the complete incoming Claude
  system context into developer input messages, marking the base item as
  `model.base_instructions`;
- omits top-level `instructions` and `tools`, sets Lite's explicit
  `parallel_tool_calls=false`/`tool_choice=auto`/turn-wide reasoning context
  (`reasoning.context=all_turns`), and sends the Lite header;
- sends bounded adapter-owned Codex turn metadata (`installation_id`,
  `session_id=prompt_cache_key`, `thread_id=claude_session_id`,
  `turn_id=request_id`, `window_id={thread}:0`, `request_kind=turn`) without
  placing per-turn IDs in the stable prompt/tool prefix;
- sends native transport projections: `session-id` + `thread-id` session
  headers (plus the historical `session_id` alias), `x-codex-installation-id`,
  `x-openai-internal-codex-responses-lite: true`, and bounded compatibility
  headers (`x-codex-window-id`, `x-codex-turn-metadata`, plus parent/subagent
  only when present); and
- accepts and round-trips incoming Codex `additional_tools` namespace items on
  the FCC `/v1/responses` adapter.

The compatibility base is intentionally short. AgentSwitchboard does not copy
the full mutable Codex client `instructions_template` or attempt to carve up
Claude Code's proprietary monolithic system prompt with heuristics. The full
Claude context is preserved for tool/harness compatibility, so this is a wire
contract adapter and not a claim that the Claude and native Codex harnesses
have identical behavior.

The model-profile snapshot follows the public structure used by the
[open-source Codex client](https://github.com/openai/codex/blob/main/codex-rs/core/src/client.rs)
and is kept in
`src/free_claude_code/core/openai_responses/codex_lite.py` so model-specific
fields do not become scattered provider conditionals. Session, compatibility,
and turn-metadata projections mirror
[`responses_metadata.rs`](https://github.com/openai/codex/blob/main/codex-rs/core/src/responses_metadata.rs)
and `build_session_headers` / `build_responses_headers` in `client.rs`.

### Installation, threading, and sticky routing

- Installation id is stable per `FCC_CONFIG_DIR`
  (`codex_installation_id`, `0600`), not per provider instance, matching the
  native stable-installation contract and preserving session affinity across
  config reloads.
- `session_id` is the Responses `prompt_cache_key`; `thread_id` is the Claude
  session id; `turn_id` is the gateway request id; `window_id` is
  `{thread}:0`. Window increment on compaction is not yet tracked because
  compaction is Claude-owned (see below).
- `x-codex-turn-state` is captured from SSE response headers and replayed
  only for retries within the same `stream_response` turn, never across
  turns, matching the native within-turn sticky-routing contract. WebSocket
  prewarm/reuse remains out of scope; SSE is the supported transport.

### Subagents

Claude subagents share the same Codex thread as their parent (the router
inherits the parent provider/model via `ParentRouteRegistry`). They are not
native Codex subagents, so FCC omits `x-openai-subagent` and
`x-codex-parent-thread-id` on root turns. The helpers accept those fields so
a future native Codex delegation path can set them explicitly without
conflating Claude tier names with Codex `review`/`compact`/
`memory_consolidation`/`collab_spawn` identities.

### Compaction

FCC does not call `/responses/compact`. Claude Code owns compaction and
resends summarized history as normal `/messages` turns; the Lite prefix IDs
stay stable across those turns when the thread and tool set are unchanged,
and `ParentRouteRegistry` keeps the pre-compact parent route for the same
session and provider generation. Server-side Codex compaction
(`trigger`/`reason`/`implementation`/`phase`/`strategy`) and
`history_ingest_requested` remain out of scope.

## Local Ultracode label

The local Admin surfaces expose `ultracode` for every model route as an FCC
client-facing reasoning label. It is intentionally mapped to the audited
provider-neutral `xhigh` effort before provider request construction. FCC does
not claim that any private upstream accepts a literal `ultra` wire value.

## Cache contract

- Codex integration must not replace the Luna controller for ordinary Claude Code turns.
- Any Codex helper/tool schema must be fixed for the lifetime of a Claude session and registered before the first cacheable turn.
- Do not inject per-turn timestamps, random ids, absolute app/plugin paths, auth metadata, or dynamic tool-discovery results into Luna's stable system/tool prefix.
- Codex results are bounded suffix/tool-result observations only.
- Existing stable-prefix and prompt-cache-key invariants remain authoritative; a Codex helper call must not mutate prior serialized history or tool schemas.
- Cache acceptance requires byte-stable prefix hashes across no-helper turns and across a helper turn except for the newly appended suffix.

## Authentication

- Prefer Codex's own ChatGPT subscription sign-in and stored credentials.
- AgentSwitchboard must not ask for, copy, store, or synthesize an OpenAI API key for this path.
- When launching Codex subscription commands, remove `OPENAI_API_KEY` and `CODEX_API_KEY` from the child environment so unrelated API credentials cannot accidentally override the stored ChatGPT auth mode.
- Connection is explicit user intent and must integrate with the shared provider/subscription isolation policy.

## Computer Use

Do not copy or reimplement the Codex Computer Use runtime.

The target is the installed OpenAI-managed Computer Use plugin/service used by the Codex desktop app. The signed helper has launch-context constraints on macOS, so AgentSwitchboard must not claim native parity by directly executing `SkyComputerUseClient` from an arbitrary parent process.

Preferred order:

1. detect a usable Codex desktop installation and its managed plugin state;
2. attach through the Codex-managed app/app-server/plugin host when that host exposes a stable local surface;
3. reuse the exact managed Computer Use tool schemas/implementation;
4. fail closed with a typed diagnostic when the managed host is unavailable or incompatible;
5. keep AgentSwitchboard Appshot as screenshot-only fallback, not a fake replacement for full Computer Use.

Native-parity acceptance must compare the same installed Codex build/plugin through native Codex Desktop and through the AgentSwitchboard adapter for tool discovery, screenshots/AX state, click/type/scroll/key actions, permission behavior, cancellation, and error semantics.

## Release boundary

This work must not be added to the frozen 4.30.27 release train. It should ride the next semantic-versioned release after exact-head CI and local Apple-silicon device receipts.
