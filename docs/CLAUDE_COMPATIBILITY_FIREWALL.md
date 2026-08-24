# Claude Code compatibility firewall

Tracks #31. This document defines the compatibility contract for surviving Claude Code updates without silently bypassing FCC or corrupting stream/tool semantics.

## Principle

Claude Code is an external moving dependency. FCC should treat each Claude version like a protocol dependency that must be certified before promotion.

A Claude update is not considered compatible because it launches. It is compatible only when the literal executable proves it routes through FCC and passes the required black-box contracts.

## Known-good version policy

FCC-launched sessions keep the Claude auto-updater disabled.

For each FCC release record:

- certified Claude version;
- certification timestamp;
- compatibility receipt/fingerprint id;
- FCC commit/version used for certification.

A newer installed Claude version may be tested as a candidate but must not silently replace the known-good certification.

Diagnostics should distinguish at least:

- `certified`
- `candidate`
- `unknown`
- `quarantined`

## Literal executable canary

The compatibility suite must invoke the actual Claude binary, not only internal Harness request fixtures.

Required canary coverage:

1. `claude --version` / startup;
2. gateway identity evidence (`/status` or equivalent plus FCC-side receipt);
3. text-only turn;
4. reasoning/thinking turn;
5. tool call + result + continuation;
6. parallel tool calls;
7. MCP tool path;
8. image attachment path;
9. SessionStart/UserPromptSubmit/Stop hooks;
10. resume/fork session;
11. context advertisement and auto-compact behavior;
12. stream-json output;
13. permissions and `--dangerously-skip-permissions` behavior;
14. cancellation/interrupt;
15. subagent/background-agent behavior;
16. child/self-spawn behavior.

A run that succeeds through `firstParty` or any non-FCC route is a failure, not a pass.

## Child-process containment

When the installed Claude version exposes a supported process-wrapper mechanism such as `CLAUDE_CODE_PROCESS_WRAPPER`, FCC should use it to ensure Claude-created child/background processes inherit the gateway policy.

The wrapper must reassert the canonical FCC Claude environment rather than hand-maintaining a divergent copy. At minimum this includes:

- local `ANTHROPIC_BASE_URL`;
- FCC auth token;
- context/window policy;
- provider/subscription isolation policy;
- updater/feedback/error-reporting suppression where applicable;
- local proxy bypass settings required for loopback access.

The child path must never discover unrelated provider credentials and decide to route itself.

## Settings precedence

The existing fail-closed `settings.json` routing-key check remains part of the compatibility firewall. Candidate Claude versions must have a regression test proving whether settings-file `env` precedence still behaves as expected.

If precedence changes, certification stops until FCC's launcher policy is updated intentionally.

## Sanitized compatibility fingerprint

For each candidate capture hashes/types/booleans rather than user content:

- Claude version;
- FCC version/commit;
- gateway identity;
- request-envelope/request-shape hash;
- init/system/result event type set;
- stream terminal event behavior;
- tool-call/result structural fingerprint;
- reasoning field/type presence;
- hook event set;
- advertised/effective context window;
- subagent/child wrapper observation;
- attempts and fault attribution.

Do not store prompts, responses, secrets, raw image contents, or full tool arguments.

The fingerprint should tolerate safe additive metadata while surfacing semantic deltas that can alter routing, streaming, tool execution, context, or billing.

## Candidate promotion

A candidate becomes certified only when all required canary contracts pass on the same candidate binary and FCC revision.

Promotion must not require editing global user Claude configuration.

## Quarantine and rollback

When a candidate fails:

- preserve the last known-good certification;
- mark the candidate quarantined with the failed contract/receipt;
- do not weaken routing/auth/context policy to force compatibility;
- do not auto-patch arbitrary Claude internals;
- provide an explicit path to invoke the last-known-good binary or install it again.

Rollback should be a launcher/runtime choice, not a destructive rewrite of `~/.claude`.

## Update-survival fixtures

Deterministic tests must simulate at least:

- new unknown additive stream/init event;
- changed settings-env precedence;
- changed unknown-model/context-window enforcement;
- child process that strips environment variables;
- request envelope with new metadata fields;
- provider/gateway silently switching from requested streaming to non-streaming;
- changed tool-call terminal shape;
- changed resume/session-id event shape.

Expected behavior:

- safe additive fields are tolerated;
- semantic contract changes fail loudly or quarantine the candidate;
- no malformed/incomplete tool execution is accepted as success;
- no candidate bypasses FCC merely because Claude changed its launch behavior.

## CI and scheduled validation

Deterministic compatibility fixtures belong in ordinary CI.

Live candidate certification is opt-in because it requires a real Claude executable/provider route. The resulting sanitized receipt should be attachable to the release review without requiring secrets in CI.

## Integration boundaries

Build on the existing pieces instead of replacing them:

- `free_claude_code.cli.claude_env`
- installed `fcc-claude` launcher
- managed Claude runtime
- #15 Muse torture suite
- #18 fault attribution
- #22 provider/subscription isolation
- #29 release-green integration surface

Do not fork/reimplement the Claude TUI or make compatibility dependent only on changelog parsing.
