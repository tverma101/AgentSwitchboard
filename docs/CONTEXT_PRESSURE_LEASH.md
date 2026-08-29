# Context pressure leash

> **Status: implementation mostly shipped; effectiveness study remains.** Current
> `main` has both layers described here: an idempotent managed global Claude
> policy and a hard artifact-backed text-tool-result governor with bounded
> visible excerpts, fail-closed structured/media handling, and secret-safe
> redaction. The remaining important gap is a controlled OFF-vs-ON black-box
> receipt showing materially lower context growth/compaction without semantic
> loss (#63/#64 follow-up).

AgentSwitchboard should treat compaction as a safety valve rather than the normal result
of accidental megadumps.

## Layer 1: managed global Claude policy

AgentSwitchboard may install a clearly delimited managed block into the global Claude
instruction surface. It must preserve unrelated user content outside the block,
be idempotent, create a recovery copy before first mutation, and uninstall only
its managed block.

The policy tells Claude to inspect size before broad reads, prefer bounded
`rg`/`grep`/`head`/`tail`/`sed`/offset-limit reads, avoid dumping lockfiles/logs/
vendored or generated content, redirect verbose build/test output to artifacts,
avoid rereading unchanged observations, tighten reads under pressure, and
checkpoint/compact before broad new exploration at critical pressure.

This layer is advisory and is never the sole enforcement mechanism.

## Layer 2: hard context governor

Oversized text-only tool results may be redirected to a private local artifact
and replaced with a truthful bounded locator/excerpt. Complete media blocks are
preserved for a routed vision-capable model by default; exact structured/media
state is never silently truncated. Structured values that cannot be safely
transformed still fail explicitly.

### Claude Code MCP boundary

`fcc-claude` also gives the launched Claude process a bounded MCP result
budget: it sets Claude Code's public `MAX_MCP_OUTPUT_TOKENS` to `12000` when
the user has not already set that variable. An explicit user value is
preserved. This protects the shared Claude conversation from a verbose local
or remote MCP result without flattening FCC Computer Use screenshots.

The FCC Computer Use server has a separate fail-closed `16 KiB` maximum for
its deterministic `tools/list` schema. A schema change that exceeds that
budget stops registration rather than silently adding another context-heavy
tool contract. This guard covers the FCC-owned server only; global third-party
servers remain registered under their existing Claude scopes, while the
launched Claude process applies the result budget to their returned MCP
content as well.

`fcc-claude` also enables Claude Code's deferred MCP tool presentation with
`ENABLE_TOOL_SEARCH=true` unless the user has already set that variable. This
keeps the ordinary named tools available while keeping their full definitions
out of the client's initial rendered context. Claude's search controller is an
Anthropic-host feature, not an OpenAI-compatible provider function, so FCC
filters its `tool_search_*` definitions and `tool_reference` history blocks at
the provider boundary instead of forwarding them as fake tools or JSON text.
The provider still receives the ordinary MCP definitions needed for direct
tool calls; this is a client registration/context optimization, not a claim
that every upstream provider implements Anthropic server-side tool search.

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
materially without reducing correctness.

The checked-in
[literal-Claude loopback A/B receipt](../smoke/receipts/context-leash-ab-2026-08-26.json)
proves the local FCC governor's redirection boundary with the installed Claude
2.1.228 client: policy-only and ungoverned runs remain materially equivalent,
while policy plus governor reduces the visible tool result and preserves the
synthetic completion marker. Claude's Bash tool capped the 2.3 MB fixture to
about 2.5 KB before FCC received it, so this receipt does not claim real-provider
or large-result model effectiveness; those remain separate acceptance gates.

## Relationship to compaction

The leash does not replace auto-compaction. It reduces avoidable pressure and
should be tested alongside the compaction conformance suite.

Tracked primarily by #63/#64 and validated alongside #58-#61.
