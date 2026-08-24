# Context pressure leash

Harness should treat compaction as a safety valve, not the normal operating mode for a Claude session.

A real session already demonstrated the pathological shape this contract is intended to prevent: tens of thousands of tokens from Bash output plus tens of thousands more from Read output, followed by immediate auto-compaction pressure.

## Two-layer design

### 1. Managed global Claude policy

FCC may install a clearly delimited managed block into the global Claude instruction surface actually read by the installed Claude client. The installer must preserve unrelated user content byte-for-byte outside the managed block, be idempotent, back up once before first mutation, and support clean uninstall.

The managed block should instruct Claude to:

- inspect size/line count before reading unknown files or printing unknown command output;
- prefer bounded `rg`, `grep`, `head`, `tail`, `sed`, Read offset/limit, and targeted `git diff` operations;
- never dump large lockfiles, logs, generated assets, vendored/minified files, or recursive trees when a targeted query is enough;
- route verbose test/build output to a local artifact and return the failing/error neighborhood plus a short summary and artifact path;
- avoid rereading unchanged content already observed in the session;
- narrow reads further as context pressure rises;
- checkpoint/compact before broad new exploration once pressure is critical.

This layer is advisory and must never be treated as the sole enforcement mechanism.

### 2. Context-pressure governor

Where the literal Claude client exposes a safe interception point, Harness should prevent oversized Bash/Read/MCP/tool-result payloads from entering the model context in full.

The preferred action order is:

1. prevent the unbounded operation at source;
2. redirect the complete output to a local artifact;
3. return a bounded truthful excerpt/summary plus stable handle/hash;
4. allow targeted bounded follow-up reads;
5. if the result cannot be safely transformed, use an explicit typed allow/fail policy rather than silently corrupting it.

The governor must not become a generic lossy truncator.

## Pressure modes

Use three conceptual modes whose exact thresholds are established by black-box client receipts rather than guessed constants:

- **NORMAL** — bounded exploration with normal output budgets.
- **CONSERVE** — tighter output/read budgets, reuse observations, no broad exploratory dumps.
- **CRITICAL** — prohibit obviously unbounded operations where the client allows enforcement; summarize/checkpoint before substantial new work.

## Output budgets

Initial experiments may test visible envelopes roughly in the 8-32 KiB range depending on tool/result class, but production defaults require usability and context-growth receipts.

Every oversized governed result should expose enough metadata for the agent to know it is partial:

- original byte/line/token estimate;
- visible byte/line/token estimate;
- `truncated_or_redirected=true`;
- full-result local artifact/handle when safe;
- deterministic full-result hash;
- excerpt strategy (head/tail/error-neighborhood/selected records);
- instruction for retrieving another bounded slice.

Never claim an excerpt is the complete result.

## Results that require special handling

Never blindly truncate:

- protocol-significant exact JSON/tool state;
- tool-call ids/results needed for continuation;
- opaque reasoning/signature state;
- patch/apply status where omitted lines could hide failure;
- compiler/test failure context required to diagnose the error;
- media/binary content;
- authentication or secrets.

Secret-bearing material should be redacted according to existing Harness policy rather than preserved as a model-accessible artifact.

## Verification contract

Use the literal installed Claude client and synthetic local fixtures before any live provider test.

Temptation fixtures should include:

- 5 MB log;
- 50K-line source/text file;
- large JSON/JSONL data;
- noisy failing test/build output;
- huge git diff;
- repeated request for an unchanged file;
- exact-state tool result that must not be altered.

Compare an ungoverned control against policy-only and policy-plus-governor runs. Record tool-output bytes/lines/token estimates, total context growth, compaction count, follow-up slice count, task success, and any semantic loss.

The leash is successful only if context growth and compaction frequency fall materially without reducing correctness.

## Relationship to compaction

The tiny-window compaction suite remains necessary. The leash does not replace auto-compaction; it reduces how often the client needs it and makes a compact boundary less likely to be caused by accidental megadumps.

Compaction tests should therefore include controlled runs with the leash disabled and enabled.

## Non-goals

- replacing Claude Code's tool system;
- silently rewriting arbitrary tool results;
- hiding useful failures from the model;
- storing user content in telemetry;
- adding provider/model-specific prompt hacks.

Tracked by #63 and #64; validated alongside #58-#61.