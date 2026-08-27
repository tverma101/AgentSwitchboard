# Codex subscription bridge — design checkpoint

This document is a placeholder design checkpoint and is not a release claim.

## Goal

Keep Claude Code + Luna as the primary controller while allowing explicit, bounded delegation to a locally installed Codex runtime authenticated with the user's ChatGPT plan. Do not require or persist a manually supplied OpenAI API key.

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
