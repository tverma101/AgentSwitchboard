# Context pressure leash

> **Status: implementation retained but disabled pending certification.** The
> repository contains the former managed global Claude policy and a hard
> artifact-backed text-tool-result governor. Standard FCC leaves both client
> context intervention and ingress governance off; the sandbox intentionally
> restores only the bounded 256K Claude context/auto-compact pair. The policy
> writer is also a no-op unless an explicitly isolated experiment exports
> `FCC_CONTEXT_GOVERNOR_ENABLED=true`. A future bounded experiment must
> produce fresh Claude compatibility evidence before the broader intervention
> is enabled.
> Earlier receipts are historical evidence, not a current behavior or
> certification claim.

AgentSwitchboard should treat compaction as a safety valve rather than the normal result
of accidental megadumps. FCC does not install model-facing context guidance in
the normal runtime.

## Layer 1: managed global Claude policy

The retained experiment code may install a clearly delimited managed block into
the global Claude instruction surface. The normal `install` command is disabled
and does not write the file. If an isolated experiment explicitly enables the
writer, it must preserve unrelated user content outside the block, be
idempotent, create a recovery copy before first mutation, and uninstall only
its managed block.

The policy tells Claude to inspect size before broad reads, prefer bounded
`rg`/`grep`/`head`/`tail`/`sed`/offset-limit reads, avoid dumping lockfiles/logs/
vendored or generated content, redirect verbose build/test output to artifacts,
avoid rereading unchanged observations, tighten reads under pressure, and
checkpoint/compact before broad new exploration at critical pressure.

This layer is advisory and is never the sole enforcement mechanism.

## Layer 2: hard context governor (currently disabled)

Oversized text-only tool results may be redirected to a private local artifact
and replaced with a truthful bounded locator/excerpt. Complete media blocks are
preserved for a routed vision-capable model by default; exact structured/media
state is never silently truncated. Structured values that cannot be safely
transformed still fail explicitly.

This FCC intervention is currently disabled by default because it is not yet
certified against the active Claude Code client. Set
`FCC_CONTEXT_GOVERNOR_ENABLED=true` only for a separately bounded experiment;
the default `false` path passes client tool results through unchanged.

### Claude Code MCP boundary

FCC does not set Claude Code's `MAX_MCP_OUTPUT_TOKENS` or other client context
settings in standard mode while this intervention is uncertified. The sandbox
exception sets only its bounded 256K context and auto-compact pair; user-owned
MCP/tool-search settings remain untouched.

The FCC Computer Use server has a separate fail-closed `16 KiB` maximum for
its deterministic `tools/list` schema. A schema change that exceeds that
budget stops registration rather than silently adding another context-heavy
tool contract. This guard covers the FCC-owned server only; global third-party
servers remain registered under their existing Claude scopes, while the
launched Claude process applies the result budget to their returned MCP
content as well.

FCC does not enable Claude Code's deferred MCP tool presentation. Claude's
search controller remains a client-owned feature. Any provider-boundary
translation required for protocol compatibility remains separate from this
disabled client policy.

Preferred action order:

1. prevent obviously unbounded work at source when possible;
2. store the complete redacted output in a private local artifact;
3. return a bounded explicit excerpt + handle/hash;
4. support targeted bounded follow-up slices;
5. fail explicitly if safe transformation is impossible.

The governor is not a generic lossy truncator.

## Pressure modes

Conceptual modes remain useful even if exact thresholds change with client
receipts:

- **NORMAL** — bounded exploration with ordinary budgets;
- **CONSERVE** — tighter output/read budgets and observation reuse;
- **CRITICAL** — no obviously unbounded exploration; checkpoint/compact before
  substantial new work.

## Result requirements

A governed result must disclose that it is partial and provide original/visible
size estimates, redirection state, artifact handle when safe, deterministic
hash, excerpt strategy, and a bounded retrieval path.

Never blindly truncate protocol-significant JSON/tool state, tool ids/results,
opaque reasoning/signature state, patch/apply status, required failure context,
media/binary content, or secrets. Secret-bearing visible excerpts and artifacts
must use the same redaction policy. `FCC_CONTEXT_GOVERNOR_PRESERVE_MEDIA=false`
restores strict oversized-media rejection for environments that explicitly
prefer that boundary.

## Verification

Use the literal Claude client with deterministic/synthetic fixtures such as a
5 MB log, 50K-line text file, large JSON/JSONL, noisy failing build, huge diff,
repeated unchanged reads, and exact-state tool results.

Compare ungoverned, policy-only, and policy+governor runs. Record tool-output
bytes/lines/token estimates, total context growth, compaction count, follow-up
slice count, task success, and semantic loss.

The leash is successful only when context growth/compaction frequency fall
materially without reducing correctness. That effectiveness claim is not made
for the current disabled runtime.

The checked-in historical
[literal-Claude loopback A/B receipt](../smoke/receipts/context-leash-ab-2026-08-26.json)
proves the former local FCC governor's redirection boundary with the installed Claude
2.1.228 client: policy-only and ungoverned runs remain materially equivalent,
while policy plus governor reduces the visible tool result and preserves the
synthetic completion marker. Claude's Bash tool capped the 2.3 MB fixture to
about 2.5 KB before FCC received it, so this receipt does not claim real-provider
or large-result model effectiveness; those remain separate acceptance gates.

## Relationship to compaction

The leash does not replace auto-compaction. Standard launches delegate
compaction entirely to Claude Code; the sandbox supplies only its bounded
window values for controlled testing. If the broader governor is explicitly
enabled in a bounded experiment, it should be tested alongside the compaction
conformance suite.

The implementation is validated alongside the compaction conformance suite. The
controlled OFF-vs-ON efficacy receipt remains a separate acceptance gate; issue
references in older records are historical traceability, not current backlog
status.
