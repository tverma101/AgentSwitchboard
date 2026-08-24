# Claude Code compaction conformance contract

This document defines the acceptance contract for #58-#61.

## Principle

Compaction is part of FCC correctness because FCC owns the client-facing context budget. A lower token count after a compact operation is not sufficient proof. The literal installed Claude Code client must prove that compaction is armed, fires before the hard limit, preserves semantic state, preserves routing, and does not destroy cache economics.

## Economical test order

1. **Unit/config tests**
   - Verify FCC injects the requested bounded context and auto-compact values.
   - These tests prove configuration only; they are not proof that Claude honors the values.

2. **Local synthetic gateway**
   - Launch the literal installed `claude` executable through FCC against a local Anthropic-compatible synthetic endpoint.
   - Prefer a 50,000-token requested FCC context window because it keeps ballast and repeated compact cycles small.
   - Record the actual effective window observed by Claude. If the installed client rejects or clamps 50K, record that result and use the smallest client-accepted window.
   - Synthetic runs must make zero Anthropic/OpenAI/Codex/OpenCode Go model requests.

3. **Semantic torture fixtures**
   - Cross a compact boundary with text, tools, reasoning state, memory/skills, media where supported, resume, and child/subagent execution surfaces.
   - Verify structural state before and after compact.

4. **Tiny live Go confirmation**
   - Only after local fixtures pass, run a bounded Muse/OpenCode Go confirmation using the smallest practical accepted window.
   - Do not run a 256K/1M context burn merely to prove auto-compact.

5. **Economic comparison**
   - Compare pre-compact, compacting, first post-compact, mature post-compact, and resume-after-compact turns.

## Requested vs effective window

Harness currently allows `FCC_CLAUDE_CONTEXT_TOKENS` from 32K to 1M and applies the resulting value to both `CLAUDE_CODE_MAX_CONTEXT_TOKENS` and `CLAUDE_CODE_AUTO_COMPACT_WINDOW`.

Claude Code itself may impose a different accepted range or clamp behavior. Therefore every receipt must distinguish:

- FCC requested context cap
- FCC requested auto-compact window
- Claude-observed/effective context window
- Claude-observed/effective compact threshold/window
- source of the value when observable

A successful environment injection is not proof of an effective 50K window.

## Base receipt schema

Every compaction receipt should contain sanitized metadata only:

- `claude_version`
- `harness_commit`
- `launch_surface`
- `requested_context_tokens`
- `effective_context_tokens`
- `requested_compact_window`
- `effective_compact_window`
- `gateway_identity_hash`
- `provider`
- `model`
- `protocol`
- `session_relationship_hash`
- `turn_index`
- `context_before_compact`
- `context_after_compact`
- `compact_trigger_observed`
- `attempts`
- `retry_reason`
- `duplicate_tool_calls`
- `ttft_ms` when available
- `duration_ms`
- `stable_prefix_hash`
- `tool_schema_hash`
- `message_shape_hash`
- `reasoning_state_presence_hash`
- `media_count_type_hash`
- `learning_injection_hash`
- cache/token/cost counters when live usage reports them

Never store prompt text, response text, screenshots, image/base64 bytes, reasoning payload text, tool arguments/results, auth material, or raw session ids in these receipts.

## Core fixtures

### Trigger correctness

- auto-compact fires before hard context failure
- manual `/compact` where supported
- 50K requested and accepted
- 50K requested but clamped/rejected
- smallest accepted-window fallback
- compact disabled/missing-window negative control
- one post-compact turn proves continued usability

### Semantic continuity

- text history
- sequential tool calls
- parallel tool calls
- committed tool side effect immediately before compact
- reasoning summary/opaque reasoning state
- reasoning plus tool call
- project/global memory injection
- generated skill availability
- image/media block where supported
- computer-use screenshot/tool-result association where supported
- interrupted/failed compact recovery

### Session/process inheritance

- fresh `fcc-claude`
- `fccdanger`
- resumed session
- forked/resumed managed session
- subagent
- background/self-spawned Claude process
- supported process-wrapper child
- resume after compact
- resume before threshold then cross compact
- candidate Claude version under #31 certification

## Semantic invariants

- tool ids and results remain correctly associated
- committed tools are never replayed after compact
- provider/model/controller do not silently change
- no `firstParty`/paid-provider escape
- no fabricated thinking/signature state
- opaque reasoning state is preserved only when required by the target protocol
- media cannot disappear silently
- memory/skills are not repeatedly duplicated into compact summaries
- system/tool/project prefix remains deterministic where semantics permit

## Economic invariants

The compacting turn may legitimately differ from steady state, but the compact boundary must not create an unbounded economic regression.

Measure at least:

- pre-compact steady state
- compacting turn
- first post-compact turn
- several mature post-compact turns
- resumed post-compact turn

Track input, cache read/write, effective uncached input, output, reasoning usage, cost, attempts, TTFT, and prefix hashes.

Target acceptance for the bounded comparable benchmark:

- healthy retry amplification remains 1.0x
- post-compact token amplification is <= 1.10x comparable/native median unless explained by semantic content
- cache behavior recovers to the comparable pre-compact/native envelope within a small number of turns
- no repeated full-history resend or duplicate learning injection

## Claude-version firewall

A Claude Code candidate version fails #31 certification if it changes any of the following without an understood/accepted compatibility update:

- effective compact window handling
- auto-compact arming/trigger behavior
- resume/subagent/child inheritance
- thinking/tool/media state across compact
- gateway identity/routing across compact
- compact request/response shape in a way that breaks Harness invariants

Status for every relevant canary is explicit: `PASS`, `FAIL`, `SKIPPED`, or `UNVERIFIED`. A skipped live run is not evidence.

## Issue ownership

- #58: trigger/effective-window conformance and tiny-window receipt
- #59: semantic continuity across compact
- #60: cache/economic parity around compact
- #61: resume/subagent/child/version inheritance
- #31/#33: generic Claude compatibility certification/quarantine
- #54/#57: reasoning/thinking presentation semantics
- #17/#18: canonical economic and fault/attempt receipt primitives

Do not create a parallel telemetry store, context-policy subsystem, or second compatibility firewall while implementing this work.
