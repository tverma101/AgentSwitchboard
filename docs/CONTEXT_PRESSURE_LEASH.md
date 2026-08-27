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
and replaced with a truthful bounded locator/excerpt. Exact structured/media
state that cannot be safely transformed must fail explicitly rather than be
silently truncated.

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
must use the same redaction policy.

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
