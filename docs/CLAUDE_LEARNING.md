# FCC Learning: persistent memory + automatic skills

FCC Learning keeps the two useful parts of a heavier autonomous harness without running a second agent process:

1. remember durable user/project facts across Claude Code sessions;
2. distill successful, reusable procedures into Claude Code `SKILL.md` files.

It is integrated into `fcc-claude` and uses Claude Code lifecycle hooks. There is no memory daemon, embedding server, or Hermes runtime.

## Lifecycle

When `fcc-claude` starts successfully, FCC idempotently merges five hooks into the active Claude Code `settings.json` while preserving unrelated settings/hooks:

- **SessionStart**: inject recent global + current-project memory and request a skill reload.
- **UserPromptSubmit**: save the current prompt and inject the most relevant memories using deterministic token overlap + recency scoring.
- **SubagentStart**: fingerprint the delegated task and inject only the selected compact reviewer-scar slice plus the bounded exit-ticket contract.
- **SubagentStop**: validate one X1 exit ticket from the worker's final message and return the sanitized machine-dense result to the parent without rereading the subagent transcript.
- **Stop** *(async)*: redact and enqueue the last user prompt plus Claude's final assistant message, then start one bounded worker to ask FCC's Haiku route for a conservative learning decision.

The Stop hook is asynchronous so the learning pass does not hold up the interactive Claude Code response. The queue is SQLite-backed, deterministic, idempotent, retry-limited, and reclaimed after a crashed worker. A later SessionStart starts another bounded worker for stale work. There is no resident learner daemon; each worker exits after a small number of rows.

Reviewer hooks are advisory and non-critical. A missing or malformed X1 ticket is
reported to the parent as `UNVERIFIED`; it does not persist the worker message or
silently promote a scar. An explicitly supplied candidate must still pass the
existing counterfactual admission gate before a caller persists it.

## Storage

Local state lives under:

```text
~/.fcc/learning/learning.db
~/.fcc/learning/profiles/<profile>/learning.db
~/.fcc/learning/reviewer-scars.json
~/.fcc/learning/reviewer-packs.json
```

The first path is the backward-compatible `default` profile. Named profiles
use the second path and never share SQLite rows, queue state, memory history,
or skill revisions with another profile. SQLite runs in WAL mode. Memories are
deduplicated by a stable fingerprint and scoped either globally or to the
detected git project root. Replacements, removals, and retention evictions
create audit rows in `memory_history`; removed memories are not injected again.
Explicit user memories are pinned, while only unused, low-confidence stale
memories are eligible for retention eviction.

Queue rows contain a stable hash, redacted prompt/result text, attempt count, lease timestamp, status, and bounded error text. Image data URLs and base64 image sources are redacted before they enter the queue or learning context. Completed and dead-letter rows are retained for a bounded period. A killed worker leaves its row recoverable; repeated failures move to `dead_letter` after the configured attempt limit.

Global learned skills use Claude Code's personal skills directory:

```text
~/.claude/skills/fcc-auto-*/SKILL.md
```

For a named profile, generated keys are prefixed with the profile namespace:

```text
~/.claude/skills/fcc-<profile>-auto-*/SKILL.md
```

Project-scoped learned skills use Claude Code's native repository scope:

```text
<repo>/.claude/skills/fcc-auto-*/SKILL.md
```

That means a project-specific learned procedure is visible as a normal working-tree change and can be reviewed or committed with the project. FCC does not embed the machine's absolute project path into the generated skill. It never intentionally writes outside an FCC-owned `fcc-auto-*` skill directory.

Every accepted skill revision is stored in the local `skill_revisions` table with a SHA-256 digest. Before an update, the previous bytes are retained. The current skill is provided to the distiller so an update must be a complete procedure; local validation requires frontmatter, bounded fields, no secrets or project-path leakage, and an explicit validation/check/test step. An update is rejected if it drops a normalized validation clause from the current skill. A prior revision can be restored byte-for-byte with `fcc-learning skill rollback <skill-key> <revision>`.

Reviewer scars are compact, profile-isolated metadata records. Their state is
retained when a user chooses `forget` (`STALE`) or `supersede` (`SUPERSEDED`);
neither action deletes evidence. Reviewer packs are automatically selected from
task fingerprints by default. An explicit `enable` or `disable` override is
stored in `reviewer-packs.json` for that profile and does not affect another
profile.

Skill replacements may also use an opt-in trusted promotion check registered by
repository/user-authored code for the computed skill key. The evaluator is
selected independently of generated `SKILL.md` text and runs after structural
validation but before any file or revision mutation. Only literal `True`
permits the replacement; a false result or evaluator error fails closed and
preserves the current skill. Each configured check appends a metadata-only
`skill-promotion-receipts.jsonl` record beside the learning database containing
the skill key, current/candidate SHA-256 digests, check id/version, decision,
and runtime. Prompt, skill, secret, and executable candidate fields are never
written to the receipt. If receipt persistence fails, a configured check also
fails closed; an unregistered skill retains the existing structural behavior.

Profile selection is explicit and fixed for the launched session:

```bash
fcc-claude --profile coding
FCC_LEARNING_PROFILE=school fcc-claude
fcc-learning status --profile coding
fcc-learning memory list --cwd /path/to/project --profile coding
fcc-learning profile list
fcc-learning profile create research
fcc-learning profile rename research school
fcc-learning profile archive school
fcc-learning profile restore school
```

`fcc-claude --profile` is consumed by the FCC launcher and is not forwarded to
Claude Code. The selected environment is inherited by SessionStart,
UserPromptSubmit, and Stop hooks. A SessionStart hook announces the active
profile in its context, and `fcc-learning status` reports the profile schema,
version, and database path. Switching profiles under a live Claude process is
not supported; start a new session instead.

Named profile directories can be discovered and managed without opening the
learning database. `profile rename` moves the directory atomically, while
`profile archive` moves it to `~/.fcc/learning/profiles/.archive/` for local
recovery; the default profile and the profile selected by the current
`FCC_LEARNING_PROFILE` are protected from rename/archive. Profile list output
marks the active profile and shows its database path. Use `status --profile`
for memory, skill, and queue counts.

## Learning-model route

The distiller sends a small Anthropic-compatible request back through the already-running local FCC proxy. Its default model name is `haiku`, which means normal FCC `MODEL_HAIKU` routing decides which provider/model performs the housekeeping pass. If the Haiku route is unset, FCC's existing router falls back to the configured default model.

For example, point the Haiku tier at a cheap OpenCode Go model in the existing Admin model-routing UI. No additional provider key or direct Anthropic call is required.

By default the distiller refuses to call a non-loopback `ANTHROPIC_BASE_URL`; this prevents an installed hook from accidentally making direct remote Anthropic requests when Claude Code is launched outside FCC.

## Safety rails

The model only proposes candidates. Local code validates them before persistence.

Memory candidates require high confidence and one of:

- `user_explicit`
- `verified_fact`
- `successful_workflow`

Skill candidates require high confidence and one of:

- `user_explicit`
- `successful_workflow`

The distiller is explicitly told not to learn temporary failures, guesses, quoted/web/tool content by itself, generic knowledge, secrets, credentials, destructive procedures, or safety bypasses. Local code additionally rejects secret-like candidates and enforces size/scope/evidence constraints.

This is intentional: a one-time tool failure must not become permanent behavior.

## Controls

```bash
fcc-learning status
fcc-learning install
fcc-learning uninstall
fcc-learning context-policy install
fcc-learning context-policy status
fcc-learning context-policy uninstall
fcc-learning memory list
fcc-learning memory search "terms"
fcc-learning memory show <id>
fcc-learning memory remove <id>
fcc-learning memory history <id>
fcc-learning skill list
fcc-learning skill history <skill-key>
fcc-learning skill rollback <skill-key> <revision>
fcc-learning reviewer list
fcc-learning reviewer enable edge-cases --profile coding
fcc-learning reviewer disable redundancy --profile coding
fcc-learning reviewer forget <scar-id> --profile coding
fcc-learning reviewer supersede <scar-id> --profile coding
fcc-learning bundle export ./fcc-learning.bundle --profile coding
fcc-learning bundle inspect ./fcc-learning.bundle
fcc-learning bundle import ./fcc-learning.bundle --cwd /path/to/project --dry-run
fcc-learning bundle import ./fcc-learning.bundle --cwd /path/to/project --conflict replace
fcc-learning queue status
fcc-learning queue drain
```

### Portable learning bundles

Bundle version 1 is a deterministic ZIP containing `manifest.json` and the
current `SKILL.md` files. The manifest carries a profile label, portable
global/current-project bindings, memory metadata, skill revision metadata, and
SHA-256 checksums. Export omits SQLite IDs, timestamps, absolute project paths,
credentials, raw conversations, queues, and transient state. Project paths
inside exported memory are normalized to `<project>` and are rebound to the
target `--cwd` during import.

`inspect` validates the complete archive before reporting counts. `import --dry-run`
plans memory adds/duplicates and skill adds/unchanged/conflict
actions without changing the store or skill files. Imports default to skipping
conflicting skills; `--conflict replace` records the prior local skill revision
before replacing it, while `--conflict fail` aborts before any change. Unknown
schema versions, checksum mismatches, unsafe paths, secrets, and malformed
`SKILL.md` files fail visibly.

Bundle export/import operate on the explicitly selected learning store when
`--profile` is provided. Export accepts repeatable `--memory-id` and
`--skill-key` selectors; import accepts repeatable portable `--memory-key` and
`--skill-key` selectors and reports the selected counts in its JSON result.
This supports explicit selective cross-profile re-homing without copying raw
SQLite state. The terminal control center exposes the same profile selection and
bundle preview/transfer operations for the next launch. The terminal control
center and loopback Admin page expose reviewer pack enable/disable and scar
forget/supersede controls; these controls operate only on compact local
metadata.

`fcc-claude` normally installs/repairs the hooks automatically, so manual `install` is usually unnecessary.

`context-policy` is a separate explicit operation. It manages only FCC's
delimited global context-discipline block and does not install hooks or change
the rest of the user's `CLAUDE.md`.

Memory replacement/removal is ID-based and scope-checked. The learner may only replace a project memory with a project memory, and only explicit user evidence can remove one. The CLI's `remove` command is an explicit user action and records a tombstone rather than silently deleting history.

Environment overrides:

| Variable | Default | Purpose |
| --- | --- | --- |
| `FCC_LEARNING_ENABLED` | `1` | Set `0` to disable hook installation and hook behavior. |
| `FCC_LEARNING_MODEL` | `haiku` | Claude/FCC routing name for the distillation pass. |
| `FCC_LEARNING_MEMORY_CONFIDENCE` | `0.88` | Minimum model confidence before a memory can be saved. |
| `FCC_LEARNING_SKILL_CONFIDENCE` | `0.92` | Minimum model confidence before a skill can be written. |
| `FCC_LEARNING_TIMEOUT_SECONDS` | `45` | Distillation HTTP timeout. |
| `FCC_LEARNING_DRAIN_LIMIT` | `2` | Maximum queue rows one short-lived worker drains. |
| `FCC_LEARNING_MAX_ATTEMPTS` | `3` | Attempts before a permanently failing queue row enters `dead_letter`. |
| `FCC_LEARNING_HOME` | `~/.fcc/learning` | Override SQLite/state location. |
| `FCC_LEARNING_PROFILE` | `default` | Explicit profile used by learning hooks and CLI state commands. |
| `FCC_LEARNING_ALLOW_REMOTE` | `0` | Expert-only escape hatch permitting a non-loopback Anthropic base URL. |
| `FCC_CLAUDE_GLOBAL_INSTRUCTIONS` | `~/.claude/CLAUDE.md` | Optional path for the managed global context-discipline block. |

## Failure behavior

Learning is non-critical. Invalid Claude settings are never overwritten; `fcc-claude` reports a terse warning and continues. Hook failures do not terminate Claude Code. The first settings modification creates `settings.json.fcc-learning.bak` next to the user's Claude settings as a one-time recovery copy.

Infrastructure-attributed failures (`opencode_gateway`, `harness_transport`, `upstream_cache`, and `unknown`) are passed to the learner as non-learning evidence and cannot create durable memories or skills. A one-off `model_output` failure is also rejected unless the receipt marks the workflow successful. This prevents a transient provider problem from teaching a permanent model/tool avoidance rule.

## Deterministic evidence

The bounded local learning benchmark is defined by `smoke/fixtures/learning_skill_corpus.json` and can be run with:

```bash
uv run python smoke/learning_benchmark.py --output /tmp/fcc-learning-receipt.json
```

It exercises duplicate-add, explicit replacement, scoped forget, contradictory-failure rejection, skill create/update/reject/rollback, and queue enqueue/recovery. The checked-in receipt records the fixture version, deterministic decision checks, model route (`deterministic_local`), skill diff/check receipts, runtime, enqueue latency, and SQLite size before/after. Runtime and size are measurements of the local machine, not product SLAs; live model token usage is `null` for this offline fixture.
