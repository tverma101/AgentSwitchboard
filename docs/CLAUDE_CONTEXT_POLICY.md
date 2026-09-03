# AgentSwitchboard Claude Code context policy

AgentSwitchboard supports two deliberately separate runtime modes:

- **Live product (`fcc-server`)**: the supported production gateway. It leaves
  Claude Code context and compaction policy under client control.
- **Sandbox (`t-fcc-server`)**: an isolated testing gateway. It may exercise
  explicitly marked compatibility controls and aliases without changing the
  live product defaults.

## Current status: live-product intervention disabled

The FCC context/compaction intervention is disabled in standard mode pending a
certified Claude Code compatibility receipt. Standard FCC does not set or
remove any of these client-owned policy values:

- `CLAUDE_CODE_MAX_CONTEXT_TOKENS`
- `CLAUDE_CODE_AUTO_COMPACT_WINDOW`
- `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`
- `DISABLE_COMPACT`
- `DISABLE_AUTO_COMPACT`
- `MAX_MCP_OUTPUT_TOKENS`
- `ENABLE_TOOL_SEARCH`

The standard launcher preserves explicit values already present in the user's
environment. `FCC_CLAUDE_CONTEXT_TOKENS` remains readable for older managed env
files. The sandbox launcher intentionally forwards it as both
`CLAUDE_CODE_MAX_CONTEXT_TOKENS` and `CLAUDE_CODE_AUTO_COMPACT_WINDOW`; its
default is 256K. This is the only restored sandbox context intervention.
`FCC_CONTEXT_GOVERNOR_ENABLED=false` remains the runtime default in both modes;
the ingress governor and MCP/tool-search policy stay disabled/client-owned.

The FCC self-spawn wrapper still protects the loopback proxy/auth boundary and
gateway discovery. It no longer requires context variables, so disabling this
policy does not make a normal FCC Claude launch fail.

## FCC reasoning alias

FCC exposes the client-facing `ultracode` label for every model route. It maps
to the strongest audited provider-neutral FCC effort, `xhigh`; it does not
pretend that every provider accepts a native literal `ultra` value.

## Explicit future experiment only

The repository retains the reversible global-instruction writer and
artifact-backed governor for future compatibility experiments. The normal
writer is disabled and is a no-op:

```bash
fcc-learning context-policy install
fcc-learning context-policy status
fcc-learning context-policy uninstall
```

`status` reports `enabled: false` under normal conditions, and `install` does
not write `CLAUDE.md`. Only an explicitly isolated experiment that exports
`FCC_CONTEXT_GOVERNOR_ENABLED=true` can exercise the retained writer. The
instruction block is advisory, while the governor can redirect oversized
text-only tool results and preserve or reject media/structured state according
to its explicit config. Any experiment must use a bounded test state directory
and produce fresh client compatibility evidence before being treated as a
supported policy. Uninstall remains enabled only so an old FCC block can be
removed safely.

The checked-in compact/resume, inheritance, and reasoning receipts are
historical boundary evidence for earlier FCC behavior. They do not certify the
current uncertified intervention, prove stale-plan ownership, or authorize
re-enabling it.

## Historical deterministic inheritance contract

The focused inheritance gate in
[`smoke/lib/claude_compaction_inheritance.py`](../smoke/lib/claude_compaction_inheritance.py)
checks the former policy at the fresh-session baseline and at resumed, forked,
child, interrupted-compaction, and candidate-upgrade boundaries. A passed
deterministic case reasserts the same bounded context/compact window, policy
hash, gateway identity, provider/model, protocol, route identity, and hashed
session/process relationship. This is retained as historical evidence while
the active FCC intervention remains disabled.

The checked-in
[inheritance contract receipt](../smoke/receipts/claude-compaction-inheritance-2026-08-24.json)
is `synthetic-only` and sets `live_provider_claim` to `false`. Its passed rows
prove the validator shape, not a Claude/provider run. The subagent and child
compaction edges remain `unverified`; interrupted recovery and candidate-version
canary remain `skipped` and quarantined until their separate evidence exists.
