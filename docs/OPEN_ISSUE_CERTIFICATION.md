# Remaining-issue certification

The remaining Harness backlog is intentionally consolidated onto shared evidence
machinery instead of one runner per GitHub issue.

## Deterministic default

List the steps first:

```bash
uv run python scripts/certify_open_issues.py --list
```

Run all deterministic steps:

```bash
uv run python scripts/certify_open_issues.py
```

Limit to one or more issue numbers:

```bash
uv run python scripts/certify_open_issues.py --issue 15 --issue 18
```

The command writes a metadata-only execution receipt to
`.smoke-results/open-issue-certification.json` by default. Deterministic steps
reuse the existing Responses-stream, fault-attribution, media, compaction,
terminal/policy, transport-benchmark, and reviewer-scar contracts.

## Live is explicit

Provider/device/literal-Claude work is never implied by a deterministic pass.
Include live steps only with:

```bash
uv run python scripts/certify_open_issues.py --live
```

Individual live tests still obey the existing documented `FCC_SMOKE_*` provider,
model, subagent, compaction, and credential controls. A missing live prerequisite
is `unverified`, not `passed`.

The Codex browser-device canary is also available directly:

```bash
uv run python scripts/smoke_codex_browser.py --family chrome
```

It creates and closes its own disposable local tab and records only counts,
sizes, and hashes. It does not invoke an OpenAI/Codex model and does not persist
tab IDs, URL/page text, or screenshot bytes.

## Native-vs-Harness failure comparison

Normalize one native OpenCode observation and one Harness observation for the
same logical scenario, then compare them with:

```bash
uv run python scripts/compare_native_harness.py native.json harness.json \
  --output comparison.json
```

The comparator is content-free. Protocol/request/prefix divergence can identify
a Harness bridge regression, matching known upstream failures preserve upstream
ownership, and insufficient evidence remains `unknown` rather than guessing.

Cache/cost comparison remains owned by the existing
`smoke/opencode_go_economics.py` evaluator; this comparator does not duplicate
its accounting policy.
