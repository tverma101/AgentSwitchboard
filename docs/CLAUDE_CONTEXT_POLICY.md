# Claude Code gateway context policy

AgentSwitchboard's FCC compatibility layer deliberately presents a bounded
context window to Claude Code even when an upstream gateway model advertises a
much larger native window.

## Default

`fcc-claude` uses **256,000 tokens** for both:

- `CLAUDE_CODE_MAX_CONTEXT_TOKENS`
- `CLAUDE_CODE_AUTO_COMPACT_WINDOW`

This keeps session behavior consistent across gateway models and prevents 1M-advertised models from silently pushing Claude Code into very long, degraded sessions.

FCC also sets `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=75` by default. Claude Code
therefore starts compaction with approximately 25% of the bounded window left
for the compaction turn and its continuation. An explicit value in the launch
environment is preserved. FCC removes inherited `DISABLE_COMPACT` and
`DISABLE_AUTO_COMPACT` so a stale shell setting cannot disable this safety
boundary.

## Override

Set `FCC_CLAUDE_CONTEXT_TOKENS` to an integer from 32,000 through 1,000,000.

Invalid or out-of-range values fail safe to 256,000.

Known model-native ceilings smaller than the configured FCC cap must win. Advertised windows larger than the configured cap do not automatically raise it.

## Unknown gateway models

FCC does not set
`CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT=1`. Current Claude Code
uses that setting to wait for an API-reported boundary for unknown gateway
models, which can allow a session to run too close to its limit. FCC supplies
an explicit bounded auto-compact window while keeping Claude Code's proactive
safety compaction active.

## Design rule

The provider's advertised context window is capability metadata, not a session-budget instruction. FCC owns the client-facing session budget.

## Global context-discipline leash

The client cap is a safety boundary, but it cannot prevent one oversized `Read`,
`cat`, JSON dump, or test log from consuming the session budget unnecessarily.
FCC can install a managed instruction block into the global Claude file at
`~/.claude/CLAUDE.md`:

```bash
fcc-learning context-policy install
fcc-learning context-policy status
fcc-learning context-policy uninstall
```

The command is explicit and reversible. It preserves all bytes outside stable
`FCC_CONTEXT_POLICY` markers, is idempotent, and creates one recovery copy at
`CLAUDE.md.fcc-context-policy.bak` before the first mutation. Set
`FCC_CLAUDE_GLOBAL_INSTRUCTIONS` when Claude's global instruction file is in a
different location. The status command reports only the path, policy version,
backup presence, and SHA-256 digests; it does not print instruction contents.

This leash is advisory: it guides the client toward bounded reads, summaries,
and reuse of observations. The live CLI compaction probe uses several bounded
stdin-fed conversation groups before Claude's automatic boundary, because a
single oversized message is not a valid continuity proof. It sends no manual
`/compact` command. It requires Claude's actual successful auto-compact
status/boundary, a resumed continuation marker, and a post-boundary Bash tool
result; the FCC cap in that probe is 50,000 tokens. The leash does not replace
the hard runtime tool-result governor at the FCC Messages/Responses ingress
boundary. That governor redirects oversized text-only tool results. For a
result containing only direct text and media blocks, it redirects only the
oversized direct text and preserves each complete media block; unsupported
structured values still fail explicitly. The same transformation is applied
to `/v1/messages/count_tokens` so Claude's context estimate matches the
payload FCC forwards.

Final provider usage receipts preserve that same estimate: input tokens, cache
reads, and cache writes are reconciled as one bounded partition, while
provider-specific totals remain diagnostic telemetry. This prevents a gateway
cache breakdown from making the Claude statusline jump beyond the preceding
`count_tokens` result.

When a bounded locator needs more detail, use the terminal-only retrieval
primitive rather than dumping the artifact wholesale:

```bash
fcc-learning context-artifact slice /path/from-the-locator.txt \
  --start-line 1 --line-count 80 --max-bytes 16384
```

The reader is confined to FCC's configured artifact directory, reports the
full-artifact hash and line/byte metadata, and returns only the requested
slice. It cannot be used to read an arbitrary path outside that directory.

The current live compact/resume evidence is recorded in the sanitized
[Muse auto-compact receipt](../smoke/receipts/muse-auto-compact-2026-08-24.json).
That receipt is evidence for one installed-client boundary, not a claim that
the advisory leash replaces the hard runtime governor.

The separate managed-session inheritance check is recorded in the sanitized
[managed fresh/resume/fork receipt](../smoke/receipts/claude-managed-resume-2026-08-24.json).
It covers one fresh managed task, one resumed task, and one forked continuation;
background and subagent inheritance remain outside that receipt.
The independent foreground Agent/subagent route has a separate
[metadata-only receipt](../smoke/receipts/claude-subagent-2026-08-24.json);
the opt-in top-level background route has a separate
[metadata-only receipt](../smoke/receipts/claude-background-subagent-2026-08-24.json).
It proves Claude 2.1.228 returning a background handle, native terminal attach,
and a routed Bash marker through FCC/OpenCode Go/Muse. The earlier
[historical receipt](../smoke/receipts/claude-background-session-2026-08-24.json)
preserves the failed daemon-lifecycle probe.

The complete execution-surface status map is recorded in the metadata-only
[Claude compatibility matrix](../smoke/receipts/claude-compatibility-matrix-2026-08-24.json).
It keeps passed, unverified, and skipped boundaries separate; the matrix does
not promote the remaining subagent-around-compact gap.

## Deterministic inheritance contract

The focused inheritance gate in
[`smoke/lib/claude_compaction_inheritance.py`](../smoke/lib/claude_compaction_inheritance.py)
checks the policy at the fresh-session baseline and at resumed, forked, child,
interrupted-compaction, and candidate-upgrade boundaries. A passed deterministic
case must reassert the same bounded context/compact window, policy hash, gateway
identity, provider/model, protocol, route identity, and hashed session/process
relationship. Explicit user overrides are accepted only when their bounded value
and source are recorded.

The checked-in
[inheritance contract receipt](../smoke/receipts/claude-compaction-inheritance-2026-08-24.json)
is `synthetic-only` and sets `live_provider_claim` to `false`. Its passed rows
prove the validator shape, not a Claude/provider run. The subagent and child
compaction edges remain `unverified`; interrupted recovery and candidate-version
canary remain `skipped` and quarantined until their separate evidence exists.
