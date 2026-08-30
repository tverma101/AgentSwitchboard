# FCC Learning session evidence boundary

FCC Learning needs session-level evidence before it can make a reliable end-of-session learning decision. Claude Code remains the agent harness; FCC only observes supported lifecycle hooks and keeps a small private evidence layer for later admission into durable docs, memory, or skills.

## Lifecycle

The relevant boundaries are different:

- **UserPromptSubmit** records a bounded/redacted explicit human prompt.
- **Stop** is a completed-turn boundary. It stages the bounded assistant result under the existing deterministic learning-queue id. Stop does **not** mean the interactive Claude session ended.
- **SessionEnd** is Claude Code's authoritative end-of-session hook. FCC uses it to reconcile human steering that may have been typed while Claude was already working.

The existing per-turn learner still runs from Stop in this implementation slice. The session exit-slip router tracked in #170 is the next layer; this document does not claim that DOCS / MEMORY / SKILLS / NOTHING routing is complete yet.

## Live human steering

Claude can drain text typed during an active turn into transcript `queued_command` attachments. The attachment type alone is not enough to prove that the content came from the human because internal/task notifications may use nearby transcript structures too.

FCC therefore accepts a queued command only with positive structural provenance:

```text
record.type == attachment
attachment.type == queued_command
attachment.commandMode == prompt
record.isSidechain != true
attachment.isMeta != true
record.isMeta != true
attachment.origin is absent
record.userType is absent or external
record session id is absent or matches the active SessionEnd session
```

Anything ambiguous is ignored.

## Transcript privacy and failure behavior

The transcript is an ephemeral input, not durable FCC memory.

FCC will read it only when:

- the resolved file is a regular `.jsonl` file below the configured Claude `projects/` directory;
- the complete file fits the hard transcript byte ceiling;
- every non-empty record fits the hard line ceiling and parses as UTF-8 JSON.

If any non-empty record is malformed, the path is untrusted, or a byte bound is exceeded, steering reconciliation is marked incomplete and **no partially recovered human steering is admitted**. Missing a candidate is preferable to assigning system/tool text human authority.

Raw transcript records, tool output, assistant reasoning, screenshots, and transcript paths are never copied into `session_evidence`.

## Supporting ledger

Session evidence lives in two small tables inside the existing FCC Learning SQLite database. This is supporting state, not a new durable-memory taxonomy.

`session_evidence` stores only bounded/redacted:

- `human_prompt`
- `human_steer`
- `turn_result`

Each event has a deterministic id derived from session/kind/source identity, and each kind has a hard row cap per session. Replayed hooks therefore do not create an unbounded duplicate trail.

`session_end_state` records whether transcript reconciliation completed and why. A later exit-slip decision can use that state to fail closed or lower evidence confidence instead of inventing a causal history.

## Durable learning remains separate

Nothing in this supporting ledger is automatically a memory or skill. The #170 exit-slip layer must still ask whether new session evidence would materially reduce future time/error for another agent with the current code, docs, skills, and memory already available.

Only after that counterfactual gate should accepted knowledge become:

- project/canonical docs,
- a small hot memory pointer backed by evidence,
- a reusable verified skill,
- or nothing.
