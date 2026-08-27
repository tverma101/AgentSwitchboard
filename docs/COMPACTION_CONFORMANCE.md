# Claude Code compaction conformance contract

> **Status: core path shipped and live-proven.** Current `main` has a literal
> Claude Code receipt proving a 50K effective window, automatic compaction,
> substantial context reduction, a post-compact tool turn, resume success, and
> continued FCC -> OpenCode Go -> Muse routing. Remaining work is deeper semantic
> torture, economics around the compact boundary, subagent-crossing-compact, and
> interrupted-compaction recovery (#59-#61).

Compaction is part of AgentSwitchboard correctness because AgentSwitchboard owns the client-facing
context budget. A lower token count alone is not enough: the literal client must
prove compaction fires before hard failure, preserves semantic state and routing,
and does not create pathological cache/economic behavior.

## Economical test order

1. unit/config tests for requested context/compact values;
2. literal Claude against a local synthetic gateway using a small accepted
   window where possible;
3. semantic fixtures across compact;
4. tiny live OpenCode Go/Muse confirmation;
5. bounded economic comparison around the compact boundary.

Do not burn a 256K/1M context merely to prove auto-compact.

## Requested vs effective window

Every receipt must distinguish AgentSwitchboard-requested context/compact values from the
Claude-observed effective values. Environment injection alone is not proof that
the client honored the requested window.

## Receipt shape

Use sanitized metadata such as Claude/AgentSwitchboard versions, launch surface,
requested/effective windows, gateway/provider/model/protocol identity,
session-relationship hash, turn index, context before/after compact, trigger
observation, attempts, duplicate-tool count, timings, structural prefix/tool
schema/message hashes, reasoning/media/learning state presence, and live usage
counters where available.

Never store prompts, responses, screenshots/media bytes, private reasoning,
tool payloads, auth material, or raw session ids.

## Semantic fixtures

Deep coverage should include text history, sequential/parallel tools, a committed
side effect immediately before compact, reasoning/opaque continuation state,
project/global learning state, media where supported, interrupted compact
recovery, fresh/resume/fork, foreground/background/subagent surfaces, process
wrapper children, and candidate Claude versions.

## Invariants

- tool ids/results stay associated;
- committed tools are never replayed after compact;
- provider/model/controller never silently change;
- no `firstParty` or paid-provider escape;
- no fabricated thinking/signature state;
- required opaque state is preserved only when protocol-significant;
- media cannot silently disappear;
- learning context is not duplicated repeatedly;
- stable system/tool/project prefixes remain deterministic where possible.

## Economics

Compare pre-compact steady state, compacting turn, first post-compact turn,
several mature post-compact turns, and resumed post-compact behavior. Track
input, cache read/write, effective uncached input, output/reasoning usage, cost,
attempts, timing, and stable-prefix hashes.

Healthy retry amplification should remain 1.0x. Any post-compact token/cache
regression must be bounded and explained rather than accepted as an accidental
full-history resend.

## Ownership

- #58: trigger/effective-window conformance (minimal gate already satisfied)
- #59: semantic continuity across compact
- #60: cache/economic parity around compact
- #61: resume/subagent/child/version inheritance
- #31: generic Claude compatibility certification
- #54-#56: reasoning presentation/capability semantics
- #17/#18: economics/fault receipt primitives

Do not create a second telemetry store, context subsystem, or compatibility
firewall while extending this work.
