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
