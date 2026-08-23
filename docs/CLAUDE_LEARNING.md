# FCC Learning: persistent memory + automatic skills

FCC Learning keeps the two useful parts of a heavier autonomous harness without running a second agent process:

1. remember durable user/project facts across Claude Code sessions;
2. distill successful, reusable procedures into Claude Code `SKILL.md` files.

It is integrated into `fcc-claude` and uses Claude Code lifecycle hooks. There is no memory daemon, embedding server, or Hermes runtime.

## Lifecycle

When `fcc-claude` starts successfully, FCC idempotently merges three hooks into the active Claude Code `settings.json` while preserving unrelated settings/hooks:

- **SessionStart**: inject recent global + current-project memory and request a skill reload.
- **UserPromptSubmit**: save the current prompt and inject the most relevant memories using deterministic token overlap + recency scoring.
- **Stop** *(async)*: pair the last user prompt with Claude's final assistant message and ask FCC's Haiku route for a conservative learning decision.

The Stop hook is asynchronous so the learning pass does not hold up the interactive Claude Code response.

## Storage

Local state lives under:

```text
~/.fcc/learning/learning.db
```

SQLite runs in WAL mode. Memories are deduplicated by a stable fingerprint and scoped either globally or to the detected git project root.

Automatically learned skills are written under Claude's personal skill directory with an FCC-owned prefix:

```text
~/.claude/skills/fcc-auto-*/SKILL.md
```

Project-scoped skills include the project name/path in their generated scope and description so they are not intended for unrelated repositories. FCC never overwrites skill directories that do not use the `fcc-auto-` prefix.

## Learning-model route

The distiller sends a small Anthropic-compatible request back through the already-running local FCC proxy. Its default model name is `haiku`, which means normal FCC `MODEL_HAIKU` routing decides which provider/model performs the housekeeping pass.

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
```

`fcc-claude` normally installs/repairs the hooks automatically, so manual `install` is usually unnecessary.

Environment overrides:

| Variable | Default | Purpose |
| --- | --- | --- |
| `FCC_LEARNING_ENABLED` | `1` | Set `0` to disable hook installation and hook behavior. |
| `FCC_LEARNING_MODEL` | `haiku` | Claude/FCC routing name for the distillation pass. |
| `FCC_LEARNING_MEMORY_CONFIDENCE` | `0.88` | Minimum model confidence before a memory can be saved. |
| `FCC_LEARNING_SKILL_CONFIDENCE` | `0.92` | Minimum model confidence before a skill can be written. |
| `FCC_LEARNING_TIMEOUT_SECONDS` | `45` | Distillation HTTP timeout. |
| `FCC_LEARNING_HOME` | `~/.fcc/learning` | Override SQLite/state location. |
| `FCC_LEARNING_ALLOW_REMOTE` | `0` | Expert-only escape hatch permitting a non-loopback Anthropic base URL. |

## Failure behavior

Learning is non-critical. Invalid Claude settings are never overwritten; `fcc-claude` reports a terse warning and continues. Hook failures do not terminate Claude Code. The first settings modification creates `settings.json.fcc-learning.bak` next to the user's Claude settings as a one-time recovery copy.
