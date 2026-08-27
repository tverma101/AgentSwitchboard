# Reviewer/scar upstream notes

`free_claude_code.learning.reviewer_scars` is a small, local evidence registry
for parent/subagent review work. It stores only typed metadata and bounded
evidence references; it does not store transcripts, prompts, hidden reasoning,
credentials, or provider responses. It does **not** import another memory runtime,
resident reflection agent, vector database, or autonomous router.

## Reference implementation

The review-pack and reflection ideas were compared with the Apache License 2.0
Letta Code reflection note at [b94afce3a9e57fec042c27bc6fb43c43e27c7774](https://github.com/letta-ai/letta-code/blob/b94afce3a9e57fec042c27bc6fb43c43e27c7774/src/agent/subagents/builtin/reflection.md).
AgentSwitchboard does not vendor that runtime or copy its transcript/memory behavior.

The local adaptation keeps only these ideas:

- choose the smallest review pack from explicit task signals;
- admit a scar only when a concrete prevented-pain class and evidence state are
  present;
- deduplicate by a semantic identifier and retain state history;
- inject a bounded, deterministic slice into a later review context;
- default to no persistent update for one-off, ephemeral, or already-captured
  candidates;
- prioritize corrections and contradictions over generic summaries;
- review for secrets, stale content, duplication, and misplaced information.

AgentSwitchboard deliberately rejects Letta-specific mechanics:

- no Letta agent/runtime dependency;
- no transcript-backed lifelong memory repository;
- no Git-authored reflection commits;
- no background subagent with broad filesystem edit authority;
- no second skill store or promotion mechanism;
- no persistence based only on model confidence.

FCC instead adds a stricter counterfactual gate: a scar can persist only when it
has concrete evidence and would have prevented a named class of meaningful pain
(data loss, false completion, provider spend, hours of debugging, or dangerous
duplication). Compact records remain profile-isolated and metadata-only.

The local contract deliberately excludes automatic background edits, provider
calls, and unbounded context growth. A real parent/subagent integration and A/B
canary remain separate acceptance work; deterministic contracts must not be
reported as that live evidence.
