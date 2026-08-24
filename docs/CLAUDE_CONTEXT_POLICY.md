# Claude Code gateway context policy

FCC deliberately presents a bounded context window to Claude Code even when an upstream gateway model advertises a much larger native window.

## Default

`fcc-claude` uses **256,000 tokens** for both:

- `CLAUDE_CODE_MAX_CONTEXT_TOKENS`
- `CLAUDE_CODE_AUTO_COMPACT_WINDOW`

This keeps session behavior consistent across gateway models and prevents 1M-advertised models from silently pushing Claude Code into very long, degraded sessions.

## Override

Set `FCC_CLAUDE_CONTEXT_TOKENS` to an integer from 32,000 through 1,000,000.

Invalid or out-of-range values fail safe to 256,000.

Known model-native ceilings smaller than the configured FCC cap must win. Advertised windows larger than the configured cap do not automatically raise it.

## Unknown gateway models

FCC sets `CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT=1` because FCC already supplies an explicit bounded context value. This prevents Claude Code's separate unknown-model fallback from forcing third-party gateway models back to 200K.

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
stdin-fed conversation groups before `/compact`, because Claude cannot compact
a single oversized message. It requires Claude's actual successful compact
status/boundary and a resumed continuation marker; the FCC cap in that probe is
50,000 tokens. The leash does not replace a future runtime tool-result
governor.
