# Claude Code compatibility firewall

> **Status: partially shipped, with remaining certification work.** Current
> `main` already pins/certifies Claude Code `2.1.228`, applies fail-closed
> routing-env checks, installs the supported process-wrapper boundary, and has
> black-box receipts for fresh/resume/fork, compact/resume, foreground
> subagents, background attach/tool execution, steering, and queued prompts.
> Candidate-version promotion/quarantine and the exhaustive compatibility matrix
> below remain active design work. The former receipt-only issue reference is
> retained only in historical issue records, not as an open-backlog claim.

Claude Code is an external moving dependency. AgentSwitchboard should treat each Claude
version like a protocol dependency that must be certified before promotion.
Launching is not sufficient evidence: the literal executable must prove it
routes through FCC and preserves required stream/tool/session behavior.

## Known-good policy

For each release keep the certified Claude version, certification timestamp or
receipt, FCC version/commit, and compatibility fingerprint. Diagnostics should
separate `certified`, `candidate`, `unknown`, and `quarantined` states. A newer
installed Claude must not silently replace the known-good path.

## Literal executable canary

Candidate certification should cover, as applicable:

1. version/startup and gateway identity;
2. text turn;
3. reasoning/thinking turn;
4. tool call/result/continuation;
5. parallel tools;
6. MCP path;
7. image attachment path;
8. lifecycle hooks;
9. resume/fork;
10. context advertisement and auto-compact;
11. stream-json;
12. permissions and `--dangerously-skip-permissions`;
13. cancellation/interrupt;
14. steering and queued follow-up prompts;
15. subagent/background behavior;
16. child/self-spawn behavior.

A successful turn through `firstParty` or another unintended route is a
certification failure.

## Child-process containment

When the installed Claude version exposes a supported process-wrapper mechanism,
AgentSwitchboard should reassert the canonical FCC environment for child/background
processes rather than maintain a divergent copy. This includes local gateway
routing/auth, context policy, provider isolation, updater/reporting suppression
where applicable, and loopback proxy bypass requirements.

Child processes must never inspect unrelated credentials and independently pick
a provider.

## Settings precedence

The fail-closed settings/env routing conflict check remains part of the
firewall. Each candidate version must prove that settings precedence still
behaves as expected. If precedence changes, certification stops until AgentSwitchboard
updates intentionally.

## Sanitized fingerprint

Capture structural metadata only: Claude/FCC versions, gateway identity,
request-shape hash, event type set, terminal-event behavior, tool structural
fingerprint, reasoning-field presence, hook set, effective context window,
subagent/child wrapper observation, attempts, and fault attribution.

Do not retain prompts, responses, secrets, raw image contents, full tool
arguments, or raw session ids.

## Candidate promotion and quarantine

A candidate becomes certified only when required canaries pass on the same
binary and AgentSwitchboard revision. If it fails, preserve the last known-good
certification, mark the candidate quarantined with the failing contract, do not
weaken routing/auth/context policy, and provide an explicit rollback path.

Rollback should be a launcher/runtime choice rather than destructive mutation
of the user's Claude state. The launcher may automatically select an exact
known-good executable already on PATH or configured with
`FCC_CLAUDE_KNOWN_GOOD_BINARY`. If it is not installed but the exact package is
already in npm's local cache, FCC may restore it under its private versioned
directory with network access disabled. It must never silently set
`FCC_CLAUDE_ALLOW_UNCERTIFIED=1`, substitute a merely older unverified binary,
or overwrite a pre-existing user directory.

## Update-survival fixtures

Deterministic tests should simulate additive stream events, settings precedence
changes, context-window behavior changes, stripped child environments, new
request metadata, streaming-mode changes, tool-terminal-shape changes, and
resume/session-id shape changes.

Safe additive fields may be tolerated; semantic changes must fail loudly or
quarantine the candidate. No incomplete tool execution or route bypass may be
accepted as success.

## CI boundary

Deterministic compatibility fixtures belong in ordinary CI. Live candidate
certification remains opt-in because it requires the literal external client
and provider route; only sanitized receipts should be committed.

Do not fork/reimplement the Claude TUI or make compatibility depend only on
changelog parsing.
