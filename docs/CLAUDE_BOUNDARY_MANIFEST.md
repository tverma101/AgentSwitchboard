# Claude boundary ownership

AgentSwitchboard keeps Claude Code as the harness. FCC interposes only where a provider-facing contract needs adaptation or where a boundary must fail closed.

Every Claude-facing capability belongs to one of three categories:

| Capability | FCC disposition | Boundary rule |
| --- | --- | --- |
| Planner / agent loop | **DELEGATE** | Claude Code owns planning and iteration. |
| TUI / composer / live input queue | **DELEGATE** | Claude Code owns queueing and steering UX; FCC preserves resulting message semantics. |
| Built-in subagent orchestration | **DELEGATE** | Claude owns orchestration; FCC only contains inherited provider/policy routing. |
| Permissions and session UX | **DELEGATE** | Do not recreate Claude permission/session machinery. |
| Hook lifecycle | **DELEGATE** | Use supported hooks; FCC may attach bounded context but does not replace the lifecycle. |
| Client compaction decision and UI | **DELEGATE** | Preserve Claude's supported compaction path; adapt only provider/context limits that cross the gateway. |
| MCP registration/loading | **DELEGATE** where Claude supports it | Register compatible MCP surfaces and let Claude own discovery/loading. |
| Model/provider IDs | **TRANSLATE** | Map the Claude-facing model choice to the selected provider route. |
| Anthropic Messages to provider protocol | **TRANSLATE** | Preserve semantics for Responses/Chat/native Messages. |
| Tool call/result identity | **TRANSLATE** | Preserve IDs, ordering, and result dependencies exactly. |
| Images/media | **TRANSLATE** | Convert only when the provider requires a different representation; reject lossy mappings. |
| Reasoning continuation metadata | **TRANSLATE** | Preserve provider continuation state without exposing raw private reasoning. |
| Usage/cache/session affinity | **TRANSLATE** | Keep provider continuation and accounting attached to the Claude session. |
| Unsupported non-null request extension | **REJECT** | Never silently delete semantic input on a translating route. |
| Provider-managed tool with no equivalent | **REJECT** | Fail with an actionable compatibility error. |
| Structured/media state that would be flattened | **REJECT** | Do not stringify away protocol state. |
| Route escape from FCC policy | **REJECT / QUARANTINE** | Fail closed rather than falling back around FCC. |
| Future Claude major contract | **QUARANTINE** | Widen the compatibility envelope only after contract review/canary. |
| Explicit known-bad Claude release | **QUARANTINE** | Keep exact known-good rollback available. |

## Default decision rule

1. **Can Claude Code already own this behavior while FCC preserves the boundary?** Delegate it.
2. **Does the selected provider require a different wire representation?** Translate the smallest semantics-preserving surface.
3. **Can FCC not preserve the meaning exactly enough?** Reject or quarantine it.

There is deliberately no default `REIMPLEMENT` category. A new FCC subsystem needs a separately demonstrated gap and architecture decision.

## Compatibility evidence

Use existing FCC tests and merged history first, then official/public Claude Code docs and reproducible issues, then mature public Claude-compatible proxies and open-source harness references such as Codex for generic state-machine patterns. Literal Claude/device canaries are reserved for opaque or version-sensitive properties and concrete regression signals.

## Change rule

Any PR that changes a Claude/provider compatibility boundary should keep this manifest true. New Claude fields must be delegated/passed through, explicitly translated, or rejected; they must not silently disappear.

Tracks #182.
